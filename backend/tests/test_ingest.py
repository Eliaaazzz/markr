"""Unit tests for XML parsing and whole-document validation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ingest import IngestError, parse_document

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parses_the_brief_example():
    doc = parse_document(fixture("valid_single.xml"))
    assert doc.accepted == 1
    (row,) = doc.rows
    assert row.test_id == "1234"
    assert row.student_number == "521585128"
    assert row.first_name == "Jane"
    assert row.last_name == "Austen"
    assert row.marks_available == 20
    assert row.marks_obtained == 13
    assert row.scanned_at == datetime(
        2017, 12, 4, 12, 12, 10, tzinfo=timezone(timedelta(hours=11))
    )


def test_trims_whitespace_and_preserves_leading_zeros():
    raw = b"""<mcq-test-results>
        <mcq-test-result>
            <student-number> 002299 </student-number>
            <test-id> 9863 </test-id>
            <summary-marks available=" 20 " obtained=" 13 " />
        </mcq-test-result>
    </mcq-test-results>"""
    (row,) = parse_document(raw).rows
    assert row.student_number == "002299"
    assert row.test_id == "9863"
    assert row.marks_available == 20
    assert row.marks_obtained == 13


def test_merges_in_document_duplicates_keeping_maximum():
    doc = parse_document(fixture("valid_multi_with_dups.xml"))
    assert doc.accepted == 3
    assert len(doc.rows) == 2
    kara = next(r for r in doc.rows if r.student_number == "1001")
    assert kara.marks_obtained == 17  # the lower re-scan must lose


def test_obtained_and_available_maxima_merge_independently():
    raw = b"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="10" obtained="8" />
        </mcq-test-result>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="6" />
        </mcq-test-result>
    </mcq-test-results>"""
    (row,) = parse_document(raw).rows
    assert row.marks_obtained == 8
    assert row.marks_available == 20


def test_same_student_on_different_tests_stays_separate():
    raw = b"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>5678</test-id>
            <summary-marks available="10" obtained="6" />
        </mcq-test-result>
    </mcq-test-results>"""
    assert len(parse_document(raw).rows) == 2


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("missing_student_number.xml", "record 2: missing student-number"),
        ("missing_test_id.xml", "record 1: missing test-id"),
        ("missing_summary.xml", "record 1: missing summary-marks"),
    ],
)
def test_missing_important_bits_reject_the_whole_document(name, expected):
    with pytest.raises(IngestError, match=expected):
        parse_document(fixture(name))


def test_malformed_xml_rejects():
    with pytest.raises(IngestError, match="Invalid XML format"):
        parse_document(fixture("malformed_unclosed_quote.xml"))


def test_empty_body_rejects():
    with pytest.raises(IngestError, match="Invalid XML format"):
        parse_document(b"")


def test_wrong_document_kind_rejects():
    with pytest.raises(IngestError, match="mcq-scanner-calibration"):
        parse_document(fixture("wrong_root.xml"))


def test_doctype_and_entities_reject():
    # The grading machines have no business declaring entities; defusing them
    # closes XXE and expansion bombs.
    with pytest.raises(IngestError, match="Invalid XML format"):
        parse_document(fixture("doctype_entities.xml"))


def test_obtained_above_available_rejects():
    with pytest.raises(
        IngestError, match=r"record 1: obtained marks \(21\) exceed available \(20\)"
    ):
        parse_document(fixture("obtained_gt_available.xml"))


def test_non_integer_marks_reject():
    with pytest.raises(
        IngestError, match="record 1: summary-marks 'available' must be an integer"
    ):
        parse_document(fixture("non_integer_marks.xml"))


@pytest.mark.parametrize(
    ("available", "obtained", "expected"),
    [
        ("0", "0", "record 1: summary-marks 'available' must be positive"),
        ("-5", "3", "record 1: summary-marks 'available' must be positive"),
        ("20", "-1", "record 1: summary-marks 'obtained' must not be negative"),
        ("20", "1.5", "record 1: summary-marks 'obtained' must be an integer"),
    ],
)
def test_mark_range_validation(available, obtained, expected):
    raw = f"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="{available}" obtained="{obtained}" />
        </mcq-test-result>
    </mcq-test-results>""".encode()
    with pytest.raises(IngestError, match=expected):
        parse_document(raw)


def test_missing_summary_attribute_rejects():
    raw = b"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" />
        </mcq-test-result>
    </mcq-test-results>"""
    with pytest.raises(IngestError, match="record 1: summary-marks missing 'obtained'"):
        parse_document(raw)


def test_bare_dtd_rejects_even_without_entities():
    raw = b"""<?xml version="1.0"?>
    <!DOCTYPE mcq-test-results SYSTEM "http://exams.vic/results.dtd">
    <mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>"""
    with pytest.raises(IngestError, match="Invalid XML format"):
        parse_document(raw)


def test_oversized_identifiers_reject():
    long_id = "9" * 65
    raw = f"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>{long_id}</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>""".encode()
    with pytest.raises(IngestError, match="record 1: test-id is longer than 64"):
        parse_document(raw)


def test_control_characters_in_identifiers_reject():
    raw = b"""<mcq-test-results>
        <mcq-test-result>
            <student-number>10\t01</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>"""
    with pytest.raises(
        IngestError, match="record 1: student-number contains control characters"
    ):
        parse_document(raw)


@pytest.mark.parametrize("available", ["10001", "2147483648"])
def test_marks_beyond_the_cap_reject(available):
    raw = f"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="{available}" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>""".encode()
    with pytest.raises(
        IngestError, match="record 1: summary-marks 'available' must be at most 10000"
    ):
        parse_document(raw)


def test_marks_at_the_cap_are_accepted():
    raw = b"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="10000" obtained="10000" />
        </mcq-test-result>
    </mcq-test-results>"""
    (row,) = parse_document(raw).rows
    assert row.marks_available == 10000


def test_overlong_names_are_truncated_quietly():
    long_name = "N" * 200
    raw = f"""<mcq-test-results>
        <mcq-test-result>
            <first-name>{long_name}</first-name>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>""".encode()
    (row,) = parse_document(raw).rows
    assert row.first_name is not None
    assert len(row.first_name) == 128


def test_record_count_cap_rejects_the_document(monkeypatch):
    monkeypatch.setattr("app.ingest.MAX_RECORDS", 2)
    record = """<mcq-test-result>
            <student-number>{n}</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>"""
    raw = (
        "<mcq-test-results>"
        + "".join(record.format(n=n) for n in range(3))
        + "</mcq-test-results>"
    ).encode()
    with pytest.raises(IngestError, match="holds 3 records; the limit is 2"):
        parse_document(raw)


def test_extra_fields_and_answers_are_ignored():
    doc = parse_document(fixture("extra_fields.xml"))
    assert doc.accepted == 1
    assert doc.rows[0].marks_obtained == 13


def test_names_are_optional():
    raw = b"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>"""
    (row,) = parse_document(raw).rows
    assert row.first_name is None
    assert row.last_name is None


def test_scanned_on_is_optional_and_garbage_becomes_none():
    raw = b"""<mcq-test-results>
        <mcq-test-result scanned-on="whenever mate">
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>"""
    (row,) = parse_document(raw).rows
    assert row.scanned_at is None


def test_empty_document_is_a_degenerate_success():
    doc = parse_document(fixture("empty_root.xml"))
    assert doc.accepted == 0
    assert doc.rows == []


def test_sample_file_parses_to_known_shape():
    doc = parse_document(fixture("sample_results.xml"))
    assert doc.accepted == 100
    assert len(doc.rows) == 81
    assert {r.test_id for r in doc.rows} == {"9863"}
    # student 2326 was re-scanned lower (15 then 9); the max must survive
    by_student = {r.student_number: r for r in doc.rows}
    assert by_student["2326"].marks_obtained == 15
    assert "002299" in by_student  # leading zeros preserved


def _two_scans(first: str, second: str) -> bytes:
    """One student scanned twice, with the given scanned-on values."""
    return f"""<mcq-test-results>
        <mcq-test-result scanned-on="{first}">
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
        <mcq-test-result scanned-on="{second}">
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>""".encode()


def test_merge_keeps_the_later_scan_time():
    (row,) = parse_document(
        _two_scans("2017-12-04T12:12:10+11:00", "2017-12-05T09:00:00+11:00")
    ).rows
    assert row.scanned_at == datetime(
        2017, 12, 5, 9, 0, 0, tzinfo=timezone(timedelta(hours=11))
    )


def test_merge_keeps_the_later_scan_time_regardless_of_document_order():
    (row,) = parse_document(
        _two_scans("2017-12-05T09:00:00+11:00", "2017-12-04T12:12:10+11:00")
    ).rows
    assert row.scanned_at == datetime(
        2017, 12, 5, 9, 0, 0, tzinfo=timezone(timedelta(hours=11))
    )


def test_merge_fills_in_a_missing_scan_time_from_the_other_record():
    # A scanner that omits scanned-on must not erase a timestamp another one
    # supplied for the same paper.
    (row,) = parse_document(
        b"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
        <mcq-test-result scanned-on="2017-12-04T12:12:10+11:00">
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>"""
    ).rows
    assert row.scanned_at == datetime(
        2017, 12, 4, 12, 12, 10, tzinfo=timezone(timedelta(hours=11))
    )


@pytest.mark.parametrize(
    "first,second",
    [
        ("2017-12-04T12:12:10", "2017-12-04T12:12:10+11:00"),
        ("2017-12-04T12:12:10+11:00", "2017-12-04T12:12:10"),
    ],
)
def test_merge_prefers_the_zoned_scan_time_over_a_naive_one(first, second):
    # Naive and aware datetimes raise TypeError under max(); one scanner
    # dropping its offset must not take down a whole document.
    (row,) = parse_document(_two_scans(first, second)).rows
    assert row.scanned_at is not None
    assert row.scanned_at.tzinfo is not None


def test_merge_of_two_naive_scan_times_still_keeps_the_later():
    (row,) = parse_document(
        _two_scans("2017-12-04T12:12:10", "2017-12-05T09:00:00")
    ).rows
    assert row.scanned_at == datetime(2017, 12, 5, 9, 0, 0)
    assert row.scanned_at.tzinfo is None


def test_merge_of_two_missing_scan_times_stays_none():
    raw = b"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="9" />
        </mcq-test-result>
    </mcq-test-results>"""
    (row,) = parse_document(raw).rows
    assert row.scanned_at is None
    assert row.marks_obtained == 9


def test_merge_keeps_a_scan_time_a_later_record_omits():
    # Mirror of the fill-in case: the timestamp arrives first and the record
    # without one must not wipe it.
    (row,) = parse_document(
        b"""<mcq-test-results>
        <mcq-test-result scanned-on="2017-12-04T12:12:10+11:00">
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>1234</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>"""
    ).rows
    assert row.scanned_at == datetime(
        2017, 12, 4, 12, 12, 10, tzinfo=timezone(timedelta(hours=11))
    )


@pytest.mark.parametrize(
    "bad_id",
    [
        "year/12",  # encoded slash is re-split by ASGI path decoding
        "a" + chr(92) + "b",  # backslash
        ".",  # URL-normalised away from the detail route
        "..",
        "id with spaces",
        "9863​",  # zero-width space: visually identical to 9863
        "12‮34",  # bidi override: display order lies about stored order
        "100%",
    ],
)
def test_route_unsafe_test_ids_reject_the_document(bad_id):
    raw = f"""<mcq-test-results>
        <mcq-test-result>
            <student-number>1001</student-number>
            <test-id>{bad_id}</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>""".encode()
    with pytest.raises(IngestError, match="test-id"):
        parse_document(raw)


def test_route_safe_test_ids_are_accepted():
    for good_id in ("9863", "e2e-rescan", "YEAR_12.final", "~x", "0001"):
        raw = f"""<mcq-test-results>
            <mcq-test-result>
                <student-number>1001</student-number>
                <test-id>{good_id}</test-id>
                <summary-marks available="20" obtained="8" />
            </mcq-test-result>
        </mcq-test-results>""".encode()
        (row,) = parse_document(raw).rows
        assert row.test_id == good_id


def test_student_numbers_keep_the_looser_printable_rules():
    # Student numbers never enter a URL; a legacy number with a space or
    # slash must not cost the classroom its results.
    raw = b"""<mcq-test-results>
        <mcq-test-result>
            <student-number>LEG/ACY 42</student-number>
            <test-id>9863</test-id>
            <summary-marks available="20" obtained="8" />
        </mcq-test-result>
    </mcq-test-results>"""
    (row,) = parse_document(raw).rows
    assert row.student_number == "LEG/ACY 42"
