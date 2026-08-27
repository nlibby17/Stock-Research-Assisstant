from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Security:
    ticker: str
    company: str
    sector: str


@dataclass(frozen=True)
class PriceBar:
    ticker: str
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    adjusted_close: float
    volume: int | None
    source: str
    fetched_at: datetime


@dataclass
class FundamentalSnapshot:
    ticker: str
    source: str
    fetched_at: datetime
    company: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    free_cash_flow: float | None = None
    total_revenue: float | None = None
    forward_pe: float | None = None
    trailing_pe: float | None = None
    peg_ratio: float | None = None
    price_to_sales: float | None = None
    gross_margin: float | None = None
    profit_margin: float | None = None
    return_on_equity: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    beta: float | None = None
    provider_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fetched_at"] = self.fetched_at.isoformat()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FundamentalSnapshot:
        value = dict(value)
        value["fetched_at"] = datetime.fromisoformat(value["fetched_at"])
        return cls(**value)


@dataclass
class ScoredSecurity:
    ticker: str
    company: str
    sector: str
    latest_price: float | None
    price_as_of: str | None
    metrics: dict[str, float | None]
    metric_scores: dict[str, float | None]
    component_scores: dict[str, float | None]
    component_coverage: dict[str, float]
    overall_score: float | None
    overall_coverage: float
    recommendation: str
    eligible: bool
    rank: int | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisRun:
    run_id: str
    started_at: datetime
    completed_at: datetime | None
    as_of: str
    provider: str
    universe_name: str
    model_version: str
    config_snapshot: dict[str, Any]
    status: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    checked_at: datetime
    status: str
    endpoint: str
    latency_ms: float
    cache_hit: bool
    detail: str


@dataclass(frozen=True)
class SecFiling:
    cik: str
    ticker: str
    company_name: str
    accession_number: str
    form: str
    base_form: str
    is_amendment: bool
    filing_date: date
    report_date: date | None
    acceptance_datetime: str | None
    accepted_at: datetime | None
    availability_date: date
    availability_precision: str
    primary_document: str | None
    filing_index_url: str
    primary_document_url: str | None
    source_url: str
    fetched_at: datetime


@dataclass(frozen=True)
class SecCompanyFact:
    cik: str
    ticker: str
    company_name: str
    canonical_name: str
    taxonomy: str
    concept: str
    concept_priority: int
    label: str
    description: str
    period_type: str
    unit: str
    value: Decimal
    start_date: date | None
    end_date: date
    accession_number: str
    fiscal_year: int | None
    fiscal_period: str | None
    form: str
    filed_date: date
    frame: str | None
    accepted_at: datetime | None
    availability_date: date
    availability_precision: str
    source_url: str
    fetched_at: datetime


@dataclass(frozen=True)
class SecFinancialMetric:
    metric_name: str
    period_kind: str
    value: Decimal | None
    unit: str
    start_date: date | None
    end_date: date | None
    fiscal_year: int | None
    fiscal_period: str | None
    quality: str
    formula: str
    reason: str | None
    lineage: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SecFinancialSnapshot:
    snapshot_id: str
    ticker: str
    company_name: str
    sector: str
    as_of: datetime
    built_at: datetime
    formula_version: str
    status: str
    warnings: tuple[str, ...]
    metrics: tuple[SecFinancialMetric, ...]
