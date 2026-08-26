from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
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
