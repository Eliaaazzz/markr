"""Response models for the public API."""

from pydantic import BaseModel


class ImportResult(BaseModel):
    imported: int


class Aggregate(BaseModel):
    mean: float
    stddev: float
    min: float
    max: float
    p25: float
    p50: float
    p75: float
    count: int


class HistogramBin(BaseModel):
    lower_pct: int
    upper_pct: int
    count: int


class Histogram(BaseModel):
    bins: list[HistogramBin]
    total: int


class Dashboard(BaseModel):
    aggregate: Aggregate
    histogram: Histogram


class TestSummary(BaseModel):
    test_id: str
    student_count: int
    marks_available: int


class TestList(BaseModel):
    tests: list[TestSummary]
