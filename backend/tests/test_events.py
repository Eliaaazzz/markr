"""Unit tests for the change-notification plumbing; no Postgres involved."""

import asyncio

import pytest

from app import events as events_module
from app.events import Broadcaster
from app.main import events as events_endpoint


class _Request:
    """Stands in for a client that disconnects after a few loop turns."""

    def __init__(self, patience: int):
        self.patience = patience

    async def is_disconnected(self) -> bool:
        self.patience -= 1
        return self.patience < 0


def test_event_stream_greets_relays_and_stops_on_disconnect():
    async def scenario():
        from app.main import broadcaster

        response = await events_endpoint(_Request(patience=1))
        assert response.media_type == "text/event-stream"
        chunks = response.body_iterator

        assert await chunks.__anext__() == ": connected\n\n"
        assert len(broadcaster._subscribers) == 1

        broadcaster._publish("9863")
        assert await chunks.__anext__() == "data: 9863\n\n"

        # The client goes away; the generator must end and unsubscribe.
        remaining = [chunk async for chunk in chunks]
        assert remaining == []
        assert broadcaster._subscribers == set()

    asyncio.run(scenario())


def test_slow_subscribers_are_dropped_not_blocked():
    broadcaster = Broadcaster()
    queue = broadcaster.subscribe()
    for _ in range(queue.maxsize):
        queue.put_nowait("fill")
    # A full queue must never block the listener thread; the reader catches
    # up on its next poll instead.
    broadcaster._publish("overflow")
    assert queue.qsize() == queue.maxsize
    broadcaster.unsubscribe(queue)
    broadcaster._publish("nobody-listens")  # no subscribers, no raise


def test_listener_survives_connection_drops(monkeypatch):
    broadcaster = Broadcaster()
    attempts = 0

    def failing_connect(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            broadcaster._stop.set()
        raise RuntimeError("connection refused")

    monkeypatch.setattr(events_module.psycopg, "connect", failing_connect)
    monkeypatch.setattr(events_module, "_RECONNECT_DELAY_S", 0.01)
    broadcaster._listen_forever()  # returns once stop is set
    assert attempts == 2


def test_stop_is_safe_without_a_thread_and_with_a_broken_connection():
    broadcaster = Broadcaster()

    class BrokenConn:
        def close(self):
            raise RuntimeError("already gone")

    broadcaster._conn = BrokenConn()
    broadcaster.stop()  # must swallow the close error and not raise
    assert broadcaster._stop.is_set()


def test_publish_from_the_listener_thread_lands_on_the_loop():
    async def scenario():
        broadcaster = Broadcaster()
        broadcaster._loop = asyncio.get_running_loop()
        queue = broadcaster.subscribe()
        # What the listener thread does for each notification.
        broadcaster._loop.call_soon_threadsafe(broadcaster._publish, "1234")
        payload = await asyncio.wait_for(queue.get(), timeout=2)
        assert payload == "1234"

    asyncio.run(scenario())


@pytest.mark.parametrize("prefix", ["postgresql+psycopg://", "postgresql://"])
def test_plain_dsn_speaks_libpq(monkeypatch, prefix):
    monkeypatch.setenv("DATABASE_URL", f"{prefix}u:p@h:5432/d")
    assert events_module._plain_dsn() == "postgresql://u:p@h:5432/d"


def test_event_stream_sends_keepalives_while_nothing_changes(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(main_module, "SSE_KEEPALIVE_S", 0.01)

    async def scenario():
        response = await events_endpoint(_Request(patience=1))
        chunks = response.body_iterator
        assert await chunks.__anext__() == ": connected\n\n"
        # No notification arrives, so the stream must still say something or
        # a proxy will kill the silent connection.
        assert await chunks.__anext__() == ": keepalive\n\n"
        remaining = [chunk async for chunk in chunks]
        assert remaining == []

    asyncio.run(scenario())


def test_listener_stops_mid_stream_without_publishing(monkeypatch):
    broadcaster = Broadcaster()

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, _sql):
            return None

        def notifies(self):
            # The shutdown signal lands while a notification is in flight.
            broadcaster._stop.set()
            yield type("Notice", (), {"payload": "late"})()

    monkeypatch.setattr(
        events_module.psycopg, "connect", lambda *a, **k: FakeConn()
    )
    queue = broadcaster.subscribe()
    broadcaster._listen_forever()
    assert queue.qsize() == 0  # the late notice was dropped, not published
