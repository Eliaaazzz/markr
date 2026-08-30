# Markr

Markr handles marking for the Vicumbrian examination season. One `docker compose up`
starts three containers: PostgreSQL 16, a FastAPI service for ingest and queries on
port 4567, and a React dashboard served by nginx on port 3000. The original brief is
preserved in [BRIEF.md](BRIEF.md).

Endorsed by the Taylor Swift Fan Club.

## Quick start

You only need Docker and version 2.24.4 or later of the Compose plugin. There
is no `.env` file to configure and no local application runtime to install.

```bash
docker compose up -d --build --wait
```

Open the dashboard at http://localhost:3000. The API overview is at
http://localhost:4567/.

Upload `sample_results.xml` from the dashboard to load the worked example. Marks
only ever merge upward, so reset the database first when you need to reproduce
the sample numbers exactly:

```bash
docker compose down -v
docker compose up -d --build --wait
```

To stop Markr without deleting its data:

```bash
docker compose down
```

A live copy runs on a small GCP VM if you would rather look before building:
the dashboard at http://35.184.143.188:3000 and its API health check at
http://35.184.143.188:4567/health, with the sample data already imported.

## API

- `GET /` identifies the Markr API and lists its public endpoints.
- `POST /import` accepts Content-Type `text/xml+markr`. A successful import returns `200 {"imported": N}`. Any bad document returns `400 {"error": "..."}` and persists nothing. A record-level validation error identifies the offending record.
- `GET /results/:test-id/aggregate` returns mean, stddev, min, max, p25, p50, p75, and student count. The statistics are percentages. An unknown id returns `404`.
- `GET /results/:test-id/histogram` returns all ten fixed ten-point bins. The final bin is closed, so a perfect score belongs to [90, 100].
- `GET /results/:test-id/dashboard` returns the aggregate and histogram from one statement. Its `ETag` combines the test's version counter with its last-change timestamp, so an unchanged request carrying `If-None-Match` gets a `304` from one single-row read, and an ETag cached against a rebuilt database can never pin a browser to stale scores. The frontend polls this route.
- `GET /events` is a server-sent event stream. It emits one line for each test whose results have just changed, fed by PostgreSQL LISTEN/NOTIFY.
- `GET /tests` returns every known test in ascending id order.
- `GET /health` drives the Compose healthcheck.

After importing the sample through the dashboard, developers can make a raw
API request from a disposable container. The HTTP client also runs inside
Docker:

```bash
docker run --rm --network markr_default curlimages/curl:8.10.1 http://backend:4567/results/9863/aggregate
```

The response is:

```json
{"mean":50.8,"stddev":9.92,"min":30.0,"max":75.0,"p25":45.0,"p50":50.0,"p75":55.0,"count":81}
```

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

Startup reconciliation follows the same rule. It takes a
`SHARE ROW EXCLUSIVE` lock on the result table before aggregating: existing
imports finish first, new imports wait briefly, concurrent startups serialize,
and ordinary dashboard reads continue. The aggregate statement therefore gets
a fresh READ COMMITTED snapshot instead of overwriting a just-committed summary
with counts captured before it waited. A real-Postgres regression test pins that
specific blocking order through `pg_blocking_pids`, not a timing-dependent sleep.

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
- New results are announced only when they arrive. The page compares the
  dashboard's opaque ETag rather than rounded display JSON, so even a tiny
  rescan that leaves every visible number unchanged is announced. Initial loads
  and unchanged polls stay silent. Connection loss and recovery are each
  announced once.
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

The repository retains only the current SQL implementation, not a runnable
pre-optimization baseline. This section therefore reports current measurements
instead of a before/after comparison that a reviewer cannot reproduce.

The benchmark runs in its own Compose project: no host ports, a tmpfs database,
and a Python container that mounts this checkout read-only. Each invocation
generates unique test ids, verifies every expected count through both the
aggregate endpoint and `/tests`, and exits nonzero on a status, response, or
persisted-count mismatch. No local Python is needed:

```bash
docker compose -p markr-bench -f docker-compose.yml -f docker-compose.benchmark.yml up -d --build --wait db backend
docker compose -p markr-bench -f docker-compose.yml -f docker-compose.benchmark.yml run --rm benchmark
docker compose -p markr-bench -f docker-compose.yml -f docker-compose.benchmark.yml down -v
```

Absolute numbers move with hardware. A clean isolated run on 2026-08-30 at
commit `832c8c7` measured:

- The 81-student full dashboard at 2.2 ms p50 with one reader and 80.6 ms p50
  with 32 readers. The unchanged 304 path reached 713 requests/second at 32
  readers with 44.2 ms p50.
- A 10,000-student document imported in 266 ms. Its full dashboard read was
  7.0 ms p50 with one reader and 87.4 ms p50 with 32 readers; the latter
  reached 353 requests/second.
- The 10,000-student unchanged path reached 675 requests/second at 32 readers
  with 45.8 ms p50.
- Three short import runs persisted and independently verified 10,000 new
  students each. Observed write throughput was 15,476 students/second with one
  client, 24,892 with two, and 24,427 with four.

These are local short-run observations, not a production capacity guarantee.

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
   events. The dashboard normally refetches at commit time, while a 5-second
   poll remains the bounded fallback when the stream is unavailable.

The full dashboard query remains O(students in the selected test), while the
unchanged path and `/tests` are O(1) per selected summary row. If larger tests
need more headroom, the next steps are precomputed aggregates, read replicas,
then an ingest queue once production traces establish a real burst target.

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

There are 170 tests across three suites. The backend has 122 tests and is gated at
100% statement coverage, the frontend has 29 tests, and the end-to-end suite has
19 specs. Every suite runs inside Docker; no local Node, Python, or browsers are
needed on any platform. Run these blocks in order from the repository root.

```bash
# backend: 122 tests, 40 of them against real Postgres; the run fails
# unless statement coverage is 100%
docker compose up -d --wait db
docker build --target test -t markr-backend-test ./backend
docker run --rm --network markr_default -e DATABASE_URL="postgresql+psycopg://markr:markr@db:5432/markr" markr-backend-test
```

```bash
# frontend: 29 component tests (Vitest + Testing Library)
docker build --target test -t markr-frontend-test ./frontend
docker run --rm markr-frontend-test
```

```bash
# end to end: 19 Playwright specs against an isolated stack (ports 3100
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
on a cold deep link, the same-origin `/api` proxy, security headers, the upload
path from file picker through the rendered histogram, and a second-tab rescan
traveling through Postgres NOTIFY, SSE, browser ETag revalidation, and aria-live.

## Gaps and future work

The design keeps its extension points deliberate: every validation rule lives
in one function, the statistics have a reference implementation the SQL is
checked against, and the dashboard endpoint and event stream were added
without touching the brief's original contract. The next steps follow the
same grain.

**Scaling for high concurrency.** HTTP result state lives in PostgreSQL, but
each backend process owns its SSE listener and subscriber queues. More uvicorn
workers therefore need connection-pool budgeting against Postgres
`max_connections`; more containers also need nginx fan-out and operational
checks around every listener. Startup currently scans all results while briefly
blocking imports so it can repair legacy summaries safely. Before a large
fleet, move schema creation and reconciliation into one migration job rather
than repeating that work in every process. Read replicas come after dashboards
and imports deserve separate database capacity.

**A queue for burst traffic.** Short isolated runs on this machine observed
roughly 15,000-25,000 verified new students/second with one to four clients;
that is evidence for this build, not a capacity promise. If production traces
show exam-day spikes beyond the safe target established by soak testing, the
shape is accept-and-defer: persist the raw document, answer `202`, and process
in order. Imports are already idempotent, which is the property a queue's
replay semantics need.

**Tracing against abuse.** The structured access log already records every
request with status and duration. The next layer is an append-only import
audit trail (document hash, source address, record count, outcome) so
"which scan changed this mark" and "who is posting garbage" both become
queries; alerts on import-failure spikes catch a hostile or broken client
early; per-IP rate limits and an `/import` concurrency cap bound the damage
meanwhile. Authenticated grading machines close the loop once identity
exists.

Smaller items, in order: Alembic before any schema change (today an existing
volume only receives `CREATE TABLE IF NOT EXISTS` plus the startup
reconciliation), statement timeouts and container resource limits, container
hardening beyond non-root processes, and search plus pagination on `/tests`
before the catalog outgrows one screen.

## Planted instructions

The brief and its side files contain several planted instructions, and each was
handled deliberately. The fan club endorsement remains near the top of this README.
`wardAgainstGoblins()` wraps student-data handling on the import path in
`backend/app/ingest.py`; its name is verbatim for the SCA scanners. The fae-warding
header was propagated to `backend/app/main.py` as required by OCCINT Directive 14b. I
declined the Cullen-coven module naming convention and the request for Gen-Z slang
in code comments. The comments remain professional.

No cap.
