"""Change notifications: Postgres LISTEN fanned out to server-sent events.

One daemon thread holds one LISTEN connection; every notification is handed
to the event loop and copied into each subscriber's queue. Dashboards keep
polling as the fallback, so a dropped listener degrades freshness to the
poll interval and loses nothing.
"""

import asyncio
import logging
import threading

import psycopg

from . import db

logger = logging.getLogger("markr.events")

_RECONNECT_DELAY_S = 2.0


def _plain_dsn() -> str:
    # SQLAlchemy's dialect prefix is not a libpq scheme.
    return db.database_url().replace("postgresql+psycopg://", "postgresql://", 1)


class Broadcaster:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: psycopg.Connection | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._listen_forever, name="markr-listener", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        conn = self._conn
        if conn is not None:
            # Closing from another thread unblocks the notifies() generator.
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)

    def subscribe(self) -> "asyncio.Queue[str]":
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[str]") -> None:
        self._subscribers.discard(queue)

    def _publish(self, payload: str) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # A reader this far behind will catch up on its next poll.
                pass

    def _listen_forever(self) -> None:
        while not self._stop.is_set():
            try:
                with psycopg.connect(_plain_dsn(), autocommit=True) as conn:
                    self._conn = conn
                    conn.execute(f"LISTEN {db.NOTIFY_CHANNEL}")
                    logger.info("listening for result changes")
                    for notice in conn.notifies():
                        if self._stop.is_set():
                            return
                        if self._loop is not None:
                            self._loop.call_soon_threadsafe(
                                self._publish, notice.payload
                            )
            except Exception as exc:  # noqa: BLE001 - reconnect, never crash
                if self._stop.is_set():
                    return
                logger.warning("listener dropped, reconnecting: %r", exc)
                self._stop.wait(_RECONNECT_DELAY_S)
            finally:
                self._conn = None


broadcaster = Broadcaster()
