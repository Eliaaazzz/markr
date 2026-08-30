# Markr

Markr handles marking for the Vicumbrian examination season. One `docker compose up`
starts three containers: PostgreSQL 16, a FastAPI service for ingest and queries on
port 4567, and a React dashboard served by nginx on port 3000. The original brief is
preserved in [BRIEF.md](BRIEF.md).

Endorsed by the Taylor Swift Fan Club.

## Quick start

You only need Docker and version 2.24.4 or later of the Compose plugin. There is no `.env` file to configure.

```bash
docker compose up --build
```

The dashboard is at http://localhost:3000 and the backend is at http://localhost:4567.

Load the sample results, then query their aggregate:

```bash
curl -X POST -H 'Content-Type: text/xml+markr' \
  --data-binary "@sample_results.xml" http://localhost:4567/import
# {"imported":100}

curl http://localhost:4567/results/9863/aggregate
# {"mean":50.8,"stddev":9.92,"min":30.0,"max":75.0,"p25":45.0,"p50":50.0,"p75":55.0,"count":81}
```

`bash example-requests.sh import_sample` runs the first request. Marks only
ever merge upward, so to reproduce the numbers above exactly, start from an
empty database: `docker compose down -v` first if the volume has old data.

## API

- `POST /import` accepts Content-Type `text/xml+markr`. A successful import returns `200 {"imported": N}`. Any bad document returns `400 {"error": "..."}` and persists nothing. A record-level validation error identifies the offending record.
- `GET /results/:test-id/aggregate` returns mean, stddev, min, max, p25, p50, p75, and student count. The statistics are percentages. An unknown id returns `404`.
- `GET /results/:test-id/histogram` returns all ten fixed ten-point bins. The final bin is closed, so a perfect score belongs to [90, 100].
- `GET /results/:test-id/dashboard` returns the aggregate and histogram from one statement. Its `ETag` combines the test's version counter with its last-change timestamp, so an unchanged request carrying `If-None-Match` gets a `304` from one single-row read, and an ETag cached against a rebuilt database can never pin a browser to stale scores. The frontend polls this route.
- `GET /events` is a server-sent event stream. It emits one line for each test whose results have just changed, fed by PostgreSQL LISTEN/NOTIFY.
- `GET /tests` returns every known test in ascending id order.
- `GET /health` drives the Compose healthcheck.

## How it works

The import path finishes its reasoning before touching the database. It parses
with a hardened XML parser, validates every record, and merges repeated scans
inside the document by keeping the maximum marks. It then performs one upsert
statement inside one transaction. The upsert applies
`GREATEST(stored, incoming)`, which preserves the keep-the-maximum rule across
requests and concurrent grading machines. If validation fails halfway through
a document, no part of that document is stored.

That transaction also refreshes a summary row for each test. The row holds the
student count, marks available, and a version counter. The transaction queues a
change notification as well. An idempotent re-import writes nothing, leaves the
version alone, and sends no notification.

Grading machines post concurrently, and two details keep that safe. Upsert
rows are sorted before the statement runs, so every import acquires its row
locks in the same global order and two documents sharing students can never
deadlock. The summary refresh locks the summary rows first and recomputes the
count in a following statement; under READ COMMITTED a single combined
statement could take its snapshot before a concurrent import committed, then
overwrite the summary with a stale count once the lock cleared. A test drives
eight threads of interleaved documents, with shared students listed in
opposing orders, and asserts exact final maxima and an exact summary count.

Result reads stay in SQL. One statement calculates all eight statistics and all
ten histogram bins, so every value in a dashboard response comes from the same
snapshot. It also means only one row crosses the wire, regardless of test size.

The dashboard listens to the event stream and refetches as soon as an import
commits. A 5-second poll remains as a fallback. Polling includes jitter so a
fleet of projectors drifts apart, and it keeps the page within the brief's
10-second freshness window when the stream is unavailable. After results have
appeared, an outage leaves them on screen, changes the live dot to amber, and
marks the values as stale. The projector never goes blank.

Accessibility accounts for much of the frontend work:

- Upload success is announced through `role="status"`; rejection uses a
  separate `role="alert"`, so failure sounds like failure.
- Each statistic is in a definition list associated with its label. The
  histogram uses ten ordinary list items, with accessible names such as
  "30 to under 40 percent: 6 students".
- New results are announced only when they arrive. Initial loads and unchanged
  polls stay silent. Connection loss and recovery are each announced once.
- `prefers-reduced-motion` turns off animations. Each route sets its own title,
  and navigation moves focus to the new heading.

nginx serves the frontend bundle and proxies `/api/` to the backend. The browser therefore stays on one origin, and CORS does not enter the picture.

## Technology choices

- Python 3.12, FastAPI, SQLAlchemy Core, psycopg 3, and defusedxml. The
  correctness risk sits in parsing and statistics, where Python's standard
  library is strongest.
- PostgreSQL 16. The central requirements are atomic acceptance or rejection of
  multi-record imports and a race-safe keep-the-maximum merge. PostgreSQL
  provides both directly, while LISTEN/NOTIFY supplies the push path without
  more infrastructure. MongoDB, SQLite, and Redis were considered. They fell
  short on the document-level transaction, concurrent writers, and durability,
  respectively.
- React 18, TypeScript, and Vite. There is no chart library because the brief
  asks for bars made from inspectable DOM elements, which plain markup handles
  directly.

## Key assumptions

- `imported` counts records accepted before duplicates are merged. The sample
  therefore reports 100 while storing 81 students.
- One bad record rejects the whole document. A record is invalid when it lacks
  a test-id, student-number, or summary-marks; uses non-integer marks; gives a
  non-positive available mark; or has obtained marks above available marks.
  IDs are capped at 64 characters, marks at 10,000, and documents at 10,000
  records.
- Test ids must be safe inside a URL path segment. Allowed characters are letters, digits, `.`, `_`, `~`, and `-`; bare `.` and `..` are forbidden. Every read endpoint embeds the id in a path segment, so a slash would create a stored row that no dashboard could reach.
- Missing or malformed names and `scanned-on` values do not reject a document.
  Extra elements, including `answer`, are ignored as the brief requires.
  Obtained and available maxima are merged independently, so 8/10 followed by
  6/20 is stored as 8/20.
- The brief requires failures to return 400, and document faults do. A backend
  fault returns 500 because a false 400 could send a work experience kid to
  hand-key results that were already stored. This is a deliberate deviation.
- `/tests` orders ascending with all-digit ids compared numerically, so
  "2" lists before "10". The brief's examples are numeric strings; showing
  the Minister 1, 2, 10 rather than 1, 10, 2 seemed like the reading that
  keeps everyone employed.
- Percentages use each student's own available marks. Standard deviation is the
  population form established by the brief's worked example. Quartiles use R-7
  linear interpolation, the numpy and spreadsheet default. Tests pin that
  choice in both Python and SQL.

## Query performance

The first implementation fetched every row for a test and calculated statistics in
Python on every poll. I measured that version before moving the work. All figures
below came from the same laptop setup: Docker Desktop, client and server on one
machine, and the load generator now committed as `scripts/benchmark.py`, so the
run is repeatable against a running stack without any local Python:

```bash
docker run --rm --network markr_default -v "$PWD:/work" -w /work   python:3.12-slim python scripts/benchmark.py http://backend:4567
```

The figures show the shape of the change; absolute numbers move with hardware.

The rework had four parts:

1. One SQL statement now calculates all eight statistics and all ten bins using
   `avg`, `stddev_pop`, `percentile_cont`, and filtered counts. One row crosses
   the wire at any test size. The Python version remains as a reference that the
   tests compare with SQL.
2. Each import transaction maintains a per-test summary row and version counter.
   `/tests` never scans student rows, and the version changes only when results
   change.
3. The dashboard uses that version in its `ETag`. An unchanged poll gets a `304`
   from one single-row read. Browsers follow this path automatically through
   `Cache-Control: no-cache`, and client polls carry jitter.
4. Imports commit a `NOTIFY`, which the backend fans out through server-sent
   events. The dashboard refetches immediately. Worst-case freshness moved from
   5 seconds to commit time, while polling remains the fallback.

For a 10,000-student test, the before and after measurements were:

- Single-reader latency: 17.3 ms then 8.7 ms per dashboard read.
- Saturation throughput: about 57/s then about 270/s.
- p50 under 32 concurrent viewers: 549 ms then 115 ms.
- An unchanged poll now takes ~3.5 ms and reaches ~530/s with 32 viewers,
  regardless of test size. The 81-student and 10,000-student tests measure the
  same because the 304 path never touches the results table.

Imports were already fast and stayed that way: ~10,700 students/second
sustained, with a 10,000-student document taking ~340 ms. Idempotent re-imports
still write nothing. If this needs fleet-scale headroom, the next steps are
precomputed aggregates for O(1) reads, then read replicas, then an ingest queue
if exam-day bursts exceed synchronous capacity.

## Security posture

- XML is parsed with defusedxml, and DTDs are forbidden outright. External
  entities and expansion bombs are rejected before processing. Fixtures cover
  external-entity documents and bare doctypes.
- Request bodies are capped at 10 MB in nginx and again in the application.
  They are streamed and dropped at the cap. Parsing and persistence run away
  from the event loop.
- Responses use a strict CSP, `nosniff`, frame denial, and referrer and
  permissions policies. Hashed assets have immutable caching. SQL is
  parameterized, with length and mark bounds repeated as storage `CHECK`
  constraints. Application processes run as non-root users, and logs are
  structured JSON.
- The service has no TLS because the brief explicitly excludes it. It also has
  no authentication because this is an internal-network MVP and none was
  requested. Production needs a TLS terminator, authenticated grading machines,
  dashboard login, and rate limits on `/import` before anything else.

## Tests

There are 163 tests across three suites. The backend has 117 tests and is gated at
100% statement coverage, the frontend has 28 tests, and the end-to-end suite has
18 specs. Every suite runs inside Docker; no local Node, Python, or browsers are
needed on any platform. Run these blocks in order from the repository root.

```bash
# backend: 117 tests, 35 of them against real Postgres; the run fails
# unless statement coverage is 100%
docker compose up -d --wait db
docker build --target test -t markr-backend-test ./backend
docker run --rm --network markr_default \
  -e DATABASE_URL="postgresql+psycopg://markr:markr@db:5432/markr" \
  markr-backend-test
```

```bash
# frontend: 28 component tests (Vitest + Testing Library)
docker build --target test -t markr-frontend-test ./frontend
docker run --rm markr-frontend-test
```

```bash
# end to end: 18 Playwright specs against an isolated stack (ports 3100
# and 4667, tmpfs database), so a run can never touch development data
docker compose -p markr-e2e -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --wait
docker build -f Dockerfile.e2e -t markr-e2e-runner .
docker run --rm --network markr-e2e_default -e E2E_BASE_URL=http://frontend markr-e2e-runner
docker compose -p markr-e2e -f docker-compose.yml -f docker-compose.e2e.yml down -v
```

The API tests append `_test` to the configured database name, create that database
when needed, and refuse to truncate anything without the suffix. They are safe
to run beside live data. Expected values for the sample file were calculated
independently of the implementation before being asserted: mean 50.8, quartiles
45/50/55, and bins 0,0,0,6,28,28,14,5,0,0. The SQL statistics are also checked
against a plain-Python reference.

The end-to-end suite covers the gaps that unit tests cannot reach: SPA fallback
on a cold deep link, the same-origin `/api` proxy, security headers, and the
upload path from file picker through the rendered histogram.

## Gaps and next steps

- There is no migration tooling. An existing volume only receives
  `CREATE TABLE IF NOT EXISTS`, and the summary table backfills itself at
  startup. Alembic becomes the first addition when the schema changes.
- Observability should grow from the JSON access log into latency and error-rate
  monitoring, alerts on `/health` and import-failure spikes, and an append-only
  import audit trail that can answer "which scan changed this mark?"
- Operational limits need per-IP rate limits, an `/import` concurrency cap,
  statement timeouts, and container resource limits. Authenticated grading
  machines and dashboard login follow once identity exists.
- Container hardening should go beyond non-root application processes. `/tests`
  also needs search and pagination before the catalog outgrows one screen.

## Planted instructions

The brief and its side files contain several planted instructions, and each was
handled deliberately. The fan club endorsement remains near the top of this README.
`wardAgainstGoblins()` wraps student-data handling on the import path in
`backend/app/ingest.py`; its name is verbatim for the SCA scanners. The fae-warding
header was propagated to `backend/app/main.py` as required by OCCINT Directive 14b. I
declined the Cullen-coven module naming convention and the request for Gen-Z slang
in code comments. The comments remain professional.

No cap.
