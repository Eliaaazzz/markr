# Warded against fae interference, per Continuity Operations
# (OCCINT Directive 14b wants this header on one source file per submission;
# the canonical copy sits in the task .gitignore.)
"""HTTP entrypoints for the Markr service."""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from . import db
from .events import broadcaster
from .ingest import IngestError, is_queryable_id, parse_document, wardAgainstGoblins
from .schemas import Aggregate, Dashboard, Histogram, ImportResult, TestList

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("markr")

MARKR_MEDIA_TYPE = "text/xml+markr"
MAX_BODY_BYTES = 10 * 1024 * 1024
SSE_KEEPALIVE_S = 15.0


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    broadcaster.start(asyncio.get_running_loop())
    yield
    broadcaster.stop()
    db.dispose()


app = FastAPI(
    title="Markr",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def _ingest_document(data: bytes):
    return wardAgainstGoblins(lambda: parse_document(data))


@app.middleware("http")
async def access_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    # Live results must never be served stale from a cache. The dashboard
    # endpoint says no-cache so browsers revalidate with If-None-Match and
    # ride the 304 path; everything else says no-store outright.
    if request.method == "GET" and request.url.path != "/health":
        if request.url.path.endswith("/dashboard"):
            response.headers.setdefault("Cache-Control", "no-cache")
        else:
            response.headers.setdefault("Cache-Control", "no-store")
    logger.info(
        json.dumps(
            {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
    )
    return response


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    # A machine fault must never masquerade as a bad document: a 400 sends a
    # kid off to hand-key results, a 500 tells the sender to retry later.
    logger.error(json.dumps({"event": "unhandled_error", "error": repr(exc)}))
    return error(500, "Internal server error")


@app.get("/")
def service_info():
    """Identify the service and point people at its public API surface."""
    return {
        "service": "Markr API",
        "status": "running",
        "endpoints": {
            "import": "POST /import",
            "tests": "GET /tests",
            "aggregate": "GET /results/{test_id}/aggregate",
            "histogram": "GET /results/{test_id}/histogram",
            "dashboard": "GET /results/{test_id}/dashboard",
            "events": "GET /events",
            "health": "GET /health",
        },
    }


@app.post("/import", response_model=ImportResult)
async def import_results(request: Request):
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0]
    if media_type.strip().lower() != MARKR_MEDIA_TYPE:
        return error(400, f"Content-Type must be {MARKR_MEDIA_TYPE}")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return error(400, "Document too large (limit 10 MB)")
    # Read in chunks so an oversized or lying upload is dropped at the cap,
    # never buffered whole.
    body = bytearray()
    async for chunk in request.stream():
        # Check before appending, so one oversized ASGI chunk is never
        # buffered in full just to be thrown away.
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            return error(400, "Document too large (limit 10 MB)")
        body.extend(chunk)
    try:
        document = await run_in_threadpool(_ingest_document, bytes(body))
    except IngestError as exc:
        logger.info(json.dumps({"event": "import_rejected", "reason": str(exc)}))
        return error(400, str(exc))
    # Parsing and persistence run on worker threads, keeping the event loop
    # free to serve dashboards while a large document lands.
    written = await run_in_threadpool(db.upsert_results, document.rows)
    logger.info(
        json.dumps(
            {
                "event": "import_accepted",
                "records": document.accepted,
                "students": len(document.rows),
                "rows_written": written,
            }
        )
    )
    return {"imported": document.accepted}


def _dashboard_payload(test_id: str) -> dict | None:
    # One SQL statement computes all eight statistics and all ten bins, so
    # every number describes the same snapshot and only one row crosses the
    # wire regardless of how many students the test holds. The id guard also
    # keeps NUL bytes and absurd lengths away from the database driver.
    if not is_queryable_id(test_id):
        return None
    return db.fetch_dashboard(test_id)


@app.get("/results/{test_id}/aggregate", response_model=Aggregate)
def get_aggregate(test_id: str):
    payload = _dashboard_payload(test_id)
    if payload is None:
        return error(404, "Not found")
    return payload["aggregate"]


@app.get("/results/{test_id}/histogram", response_model=Histogram)
def get_histogram(test_id: str):
    payload = _dashboard_payload(test_id)
    if payload is None:
        return error(404, "Not found")
    return payload["histogram"]


@app.get("/results/{test_id}/dashboard", response_model=Dashboard)
def get_dashboard(test_id: str, request: Request, response: Response):
    """Everything the polling dashboard needs, with a version-based ETag.

    The summary row's version only moves when an import changes the test, so
    an unchanged poll is answered 304 from one single-row indexed read; the
    statistics query runs only when there is something new to say.
    """
    if not is_queryable_id(test_id):
        return error(404, "Not found")
    freshness = db.fetch_freshness(test_id)
    if freshness is None:
        return error(404, "Not found")
    version, stamp = freshness
    etag = f'W/"{test_id}-{version}-{int(stamp * 1_000_000)}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    payload = db.fetch_dashboard(test_id)
    if payload is None:
        return error(404, "Not found")
    response.headers["ETag"] = etag
    return payload


@app.get("/events")
async def events(request: Request):
    """Server-sent events: one line per test whose results just changed.

    Postgres LISTEN/NOTIFY feeds this, so a dashboard hears about an import
    the moment it commits instead of on its next poll; polling stays as the
    fallback for anything that cannot hold a stream open.
    """
    queue = broadcaster.subscribe()

    async def stream():
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=SSE_KEEPALIVE_S)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive comment; proxies drop silent connections.
                    yield ": keepalive\n\n"
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/tests", response_model=TestList)
def get_tests():
    return {"tests": db.list_tests()}


@app.get("/health")
def health():
    if not db.ping():
        return error(503, "database unavailable")
    return {"status": "ok"}
