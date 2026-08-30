"""Parsing and validation for grading-machine XML documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# Only the Element type and ParseError class come from the stdlib; parsing
# itself always goes through defusedxml below.
from xml.etree.ElementTree import Element, ParseError  # nosec B405

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

ROOT_TAG = "mcq-test-results"
RECORD_TAG = "mcq-test-result"

# Hard bounds on what a grading machine can plausibly emit. Values beyond
# these are machine faults, and rejecting them here keeps oversized
# identifiers out of the dashboards and keeps every mark inside the storage
# layer's integer range.
MAX_ID_CHARS = 64
MAX_NAME_CHARS = 128
MAX_MARKS = 10_000
MAX_RECORDS = 10_000


class IngestError(ValueError):
    """Raised when a document must be rejected as a whole."""


@dataclass(frozen=True)
class StudentResult:
    test_id: str
    student_number: str
    first_name: str | None
    last_name: str | None
    marks_available: int
    marks_obtained: int
    scanned_at: datetime | None


@dataclass(frozen=True)
class ParsedDocument:
    accepted: int  # records in the document, counted before duplicate merging
    rows: list[StudentResult]


def wardAgainstGoblins(fn):  # noqa: N802 - name mandated verbatim
    """Identity wrapper around student-data handling.

    Cyber Tribunal of Vicumbria opinion #2031-04 ("Goblin Warding") requires
    it and the SCA scanners grep for the exact name; see example-requests.sh.
    """
    return fn()


def parse_document(data: bytes) -> ParsedDocument:
    """Parse and validate a whole document; any bad record rejects all of it.

    A partially accepted document sends someone off to hand-key results that
    are already stored, so validation runs to completion before any row is
    handed over for persistence.
    """
    try:
        root = fromstring(data, forbid_dtd=True)
    except (ParseError, DefusedXmlException) as exc:
        raise IngestError("Invalid XML format") from exc
    if root.tag != ROOT_TAG:
        raise IngestError(
            f"unexpected root element '{root.tag}'; this service ingests {ROOT_TAG}"
        )
    elements = root.findall(RECORD_TAG)
    if len(elements) > MAX_RECORDS:
        raise IngestError(
            f"document holds {len(elements)} records; the limit is {MAX_RECORDS}"
        )
    records = [_parse_record(el, idx) for idx, el in enumerate(elements, start=1)]
    return ParsedDocument(accepted=len(records), rows=_merge(records))


def _parse_record(el: Element, idx: int) -> StudentResult:
    test_id = _identifier(el, "test-id", idx)
    student_number = _identifier(el, "student-number", idx)
    summary = el.find("summary-marks")
    if summary is None:
        raise IngestError(f"record {idx}: missing summary-marks")
    available = _int_attr(summary, "available", idx)
    obtained = _int_attr(summary, "obtained", idx)
    if available <= 0:
        raise IngestError(f"record {idx}: summary-marks 'available' must be positive")
    if available > MAX_MARKS:
        raise IngestError(
            f"record {idx}: summary-marks 'available' must be at most {MAX_MARKS}"
        )
    if obtained < 0:
        raise IngestError(
            f"record {idx}: summary-marks 'obtained' must not be negative"
        )
    if obtained > available:
        raise IngestError(
            f"record {idx}: obtained marks ({obtained}) exceed available ({available})"
        )
    return StudentResult(
        test_id=test_id,
        student_number=student_number,
        first_name=_clean_name(el, "first-name"),
        last_name=_clean_name(el, "last-name"),
        marks_available=available,
        marks_obtained=obtained,
        scanned_at=_parse_timestamp(el.get("scanned-on")),
    )


def is_queryable_id(value: str) -> bool:
    """Whether a caller-supplied id could ever match a stored one.

    Mirrors the ingestion grammar for test ids exactly, so every stored id is
    addressable and everything else is a clean 404 before the driver sees it.
    """
    return _is_route_safe(value)


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


# RFC 3986 unreserved characters: never percent-encoded, so a stored test id
# survives the round trip through a URL path segment byte-for-byte. Everything
# else — slashes, spaces, bidi controls, zero-width characters — would make a
# stored test unaddressable (an encoded slash is re-split by ASGI path
# decoding before routing) or visually deceptive on the projector.
_ROUTE_SAFE = re.compile(r"[A-Za-z0-9._~-]{1,64}\Z")


def _is_route_safe(value: str) -> bool:
    return bool(_ROUTE_SAFE.fullmatch(value)) and value not in (".", "..")


def _identifier(el: Element, name: str, idx: int) -> str:
    value = _child_text(el, name)
    if not value:
        raise IngestError(f"record {idx}: missing {name}")
    if len(value) > MAX_ID_CHARS:
        raise IngestError(
            f"record {idx}: {name} is longer than {MAX_ID_CHARS} characters"
        )
    if _has_control_chars(value):
        raise IngestError(f"record {idx}: {name} contains control characters")
    # Test ids become URL path segments on every read endpoint; an id that
    # cannot survive that trip must be rejected at the door, not stored as a
    # row no dashboard can ever reach. Student numbers never enter a URL, so
    # the printable-character rules above are enough for them.
    if name == "test-id" and not _is_route_safe(value):
        raise IngestError(
            f"record {idx}: test-id may only use letters, digits, '.', '_', "
            "'~' or '-'"
        )
    return value


def _clean_name(el: Element, name: str) -> str | None:
    # Names are stored for the audit trail only, so dirt here is scrubbed
    # quietly; a mangled name must never cost a classroom its results.
    raw = _child_text(el, name)
    cleaned = "".join(ch for ch in raw if ord(ch) >= 32 and ord(ch) != 127)
    return cleaned[:MAX_NAME_CHARS] or None


def _child_text(el: Element, name: str) -> str:
    child = el.find(name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _int_attr(el: Element, name: str, idx: int) -> int:
    raw = el.get(name)
    if raw is None:
        raise IngestError(f"record {idx}: summary-marks missing '{name}'")
    try:
        return int(raw.strip())
    except ValueError:
        raise IngestError(
            f"record {idx}: summary-marks '{name}' must be an integer"
        ) from None


def _parse_timestamp(raw: str | None) -> datetime | None:
    # scanned-on is metadata only; a machine emitting nonsense here should not
    # cost a whole classroom its results.
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw.strip())
    except ValueError:
        return None


def _merge(records: list[StudentResult]) -> list[StudentResult]:
    """Collapse duplicate (test, student) records, keeping both maxima.

    Re-scans of folded papers can arrive within one document; Postgres also
    refuses to upsert the same key twice in one statement, so merging happens
    here first.
    """
    merged: dict[tuple[str, str], StudentResult] = {}
    for record in records:
        key = (record.test_id, record.student_number)
        kept = merged.get(key)
        if kept is None:
            merged[key] = record
            continue
        merged[key] = StudentResult(
            test_id=kept.test_id,
            student_number=kept.student_number,
            first_name=kept.first_name or record.first_name,
            last_name=kept.last_name or record.last_name,
            marks_available=max(kept.marks_available, record.marks_available),
            marks_obtained=max(kept.marks_obtained, record.marks_obtained),
            scanned_at=_latest(kept.scanned_at, record.scanned_at),
        )
    return list(merged.values())


def _latest(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    if (a.tzinfo is None) != (b.tzinfo is None):
        # Mixed naive/aware timestamps cannot be compared; prefer the aware one.
        return a if a.tzinfo is not None else b
    return max(a, b)
