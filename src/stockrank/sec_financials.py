from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from uuid import uuid4

from stockrank.data.sec import SecCompanyFacts
from stockrank.models import SecCompanyFact, SecFinancialMetric, SecFinancialSnapshot

FORMULA_VERSION = "sec-financials-v1.0.1"
ANNUAL_DAY_RANGE = range(330, 386)
QUARTER_DAY_RANGE = range(70, 116)
YTD_DAY_RANGE = range(116, 321)
TTM_DAY_RANGE = range(330, 386)
DURATION_CONCEPTS = (
    "revenue",
    "net_income",
    "gross_profit",
    "operating_income",
    "operating_cash_flow",
    "capital_expenditures",
    "weighted_average_diluted_shares",
    "diluted_eps",
)
INSTANT_CONCEPTS = (
    "assets",
    "liabilities",
    "stockholders_equity",
    "current_assets",
    "current_liabilities",
    "cash_and_equivalents",
    "long_term_debt_current",
    "long_term_debt_noncurrent",
    "shares_outstanding",
)
FINANCIAL_SECTOR_EXCLUSIONS = frozenset(
    {
        "free_cash_flow",
        "free_cash_flow_margin",
        "gross_margin",
        "operating_margin",
        "current_ratio",
    }
)
_UNSET = object()


@dataclass(frozen=True)
class _Observation:
    canonical_name: str
    value: Decimal
    unit: str
    start_date: date | None
    end_date: date
    fiscal_year: int | None
    fiscal_period: str | None
    quality: str
    formula: str
    facts: tuple[SecCompanyFact, ...]

    @property
    def days(self) -> int | None:
        if self.start_date is None:
            return None
        return (self.end_date - self.start_date).days + 1


def _lineage(facts: tuple[SecCompanyFact, ...]) -> tuple[dict[str, object], ...]:
    unique: dict[tuple[str, str, date | None, date, str], SecCompanyFact] = {}
    for fact in facts:
        unique[
            (
                fact.accession_number,
                fact.canonical_name,
                fact.start_date,
                fact.end_date,
                fact.concept,
            )
        ] = fact
    return tuple(
        {
            "canonical_name": fact.canonical_name,
            "taxonomy": fact.taxonomy,
            "concept": fact.concept,
            "unit": fact.unit,
            "value": str(fact.value),
            "start_date": fact.start_date.isoformat() if fact.start_date else None,
            "end_date": fact.end_date.isoformat(),
            "accession_number": fact.accession_number,
            "filed_date": fact.filed_date.isoformat(),
            "accepted_at": fact.accepted_at.isoformat() if fact.accepted_at else None,
            "availability_date": fact.availability_date.isoformat(),
            "availability_precision": fact.availability_precision,
            "source_url": fact.source_url,
        }
        for fact in sorted(
            unique.values(),
            key=lambda item: (item.end_date, item.canonical_name, item.accession_number),
        )
    )


def _reported(fact: SecCompanyFact) -> _Observation:
    return _Observation(
        canonical_name=fact.canonical_name,
        value=fact.value,
        unit=fact.unit,
        start_date=fact.start_date,
        end_date=fact.end_date,
        fiscal_year=fact.fiscal_year,
        fiscal_period=fact.fiscal_period,
        quality="reported",
        formula="reported SEC Company Fact",
        facts=(fact,),
    )


def _metric(
    name: str,
    kind: str,
    observation: _Observation | None,
    *,
    quality: str | None = None,
    formula: str | None = None,
    reason: str | None = None,
    value: Decimal | None | object = _UNSET,
    unit: str | None = None,
    facts: tuple[SecCompanyFact, ...] | None = None,
) -> SecFinancialMetric:
    return SecFinancialMetric(
        metric_name=name,
        period_kind=kind,
        value=(
            observation.value
            if value is _UNSET and observation is not None
            else None
            if value is _UNSET
            else value
        ),
        unit=unit or (observation.unit if observation else "ratio"),
        start_date=observation.start_date if observation else None,
        end_date=observation.end_date if observation else None,
        fiscal_year=observation.fiscal_year if observation else None,
        fiscal_period=observation.fiscal_period if observation else None,
        quality=quality or (observation.quality if observation else "missing"),
        formula=formula or (observation.formula if observation else FORMULA_VERSION),
        reason=reason,
        lineage=_lineage(facts if facts is not None else observation.facts if observation else ()),
    )


def _missing(name: str, kind: str, reason: str, *, quality: str = "missing") -> SecFinancialMetric:
    return _metric(name, kind, None, quality=quality, reason=reason)


def _latest(observations: list[_Observation]) -> _Observation | None:
    return max(
        observations,
        key=lambda value: (value.end_date, value.days or 0),
        default=None,
    )


def _annual(observations: list[_Observation]) -> list[_Observation]:
    values = [
        value
        for value in observations
        if value.days in ANNUAL_DAY_RANGE and value.fiscal_period == "FY"
    ]
    return sorted(values, key=lambda value: value.end_date)


def _ytd(observations: list[_Observation]) -> list[_Observation]:
    values = [
        value
        for value in observations
        if value.days is not None
        and (value.days in QUARTER_DAY_RANGE or value.days in YTD_DAY_RANGE)
        and value.fiscal_period in {"Q1", "Q2", "Q3"}
    ]
    return sorted(values, key=lambda value: value.end_date)


def _quarters(observations: list[_Observation]) -> list[_Observation]:
    direct = [value for value in observations if value.days in QUARTER_DAY_RANGE]
    derived: list[_Observation] = []
    by_start: dict[tuple[date, str], list[_Observation]] = defaultdict(list)
    for value in observations:
        if value.start_date and (
            value.days in QUARTER_DAY_RANGE
            or value.days in YTD_DAY_RANGE
            or value.days in ANNUAL_DAY_RANGE
        ):
            by_start[(value.start_date, value.unit)].append(value)
    for values in by_start.values():
        ordered = sorted(values, key=lambda value: value.end_date)
        for previous, current in pairwise(ordered):
            derived_start = previous.end_date + timedelta(days=1)
            derived_days = (current.end_date - derived_start).days + 1
            if derived_days not in QUARTER_DAY_RANGE:
                continue
            if current.canonical_name == "diluted_eps":
                # Per-share values with changing denominators are not safely
                # recoverable by subtracting cumulative EPS.
                continue
            if current.canonical_name == "weighted_average_diluted_shares":
                assert current.days is not None and previous.days is not None
                derived_value = (
                    current.value * current.days - previous.value * previous.days
                ) / Decimal(derived_days)
                formula = "day-weighted current cumulative shares minus preceding cumulative shares"
            else:
                derived_value = current.value - previous.value
                formula = "current cumulative fact minus preceding cumulative fact"
            derived.append(
                _Observation(
                    canonical_name=current.canonical_name,
                    value=derived_value,
                    unit=current.unit,
                    start_date=derived_start,
                    end_date=current.end_date,
                    fiscal_year=current.fiscal_year,
                    fiscal_period="Q4" if current.fiscal_period == "FY" else current.fiscal_period,
                    quality="derived",
                    formula=formula,
                    facts=previous.facts + current.facts,
                )
            )
    by_end: dict[date, _Observation] = {}
    for value in sorted(derived + direct, key=lambda item: item.end_date):
        current = by_end.get(value.end_date)
        if current is None or (current.quality == "derived" and value.quality == "reported"):
            by_end[value.end_date] = value
    return sorted(by_end.values(), key=lambda value: value.end_date)


def _latest_quarter_chain(quarters: list[_Observation]) -> list[_Observation]:
    for final_index in range(len(quarters) - 1, 2, -1):
        chain = quarters[final_index - 3 : final_index + 1]
        if any(
            not current.start_date
            or not 0 <= (current.start_date - previous.end_date).days - 1 <= 14
            for previous, current in pairwise(chain)
        ):
            continue
        if not chain[0].start_date:
            continue
        span = (chain[-1].end_date - chain[0].start_date).days + 1
        if span in TTM_DAY_RANGE and len({item.unit for item in chain}) == 1:
            return chain
    return []


def _ttm(observations: list[_Observation]) -> _Observation | None:
    chain = _latest_quarter_chain(_quarters(observations))
    if not chain:
        return None
    if chain[-1].canonical_name == "weighted_average_diluted_shares":
        total_days = sum(item.days or 0 for item in chain)
        if not total_days:
            return None
        value = sum((item.value * (item.days or 0) for item in chain), Decimal(0)) / Decimal(
            total_days
        )
        formula = "day-weighted average of four contiguous discrete fiscal quarters"
    else:
        value = sum((item.value for item in chain), Decimal(0))
        formula = "sum of four contiguous discrete fiscal quarters"
    return _Observation(
        canonical_name=chain[-1].canonical_name,
        value=value,
        unit=chain[-1].unit,
        start_date=chain[0].start_date,
        end_date=chain[-1].end_date,
        fiscal_year=chain[-1].fiscal_year,
        fiscal_period="TTM",
        quality="derived",
        formula=formula,
        facts=tuple(fact for item in chain for fact in item.facts),
    )


def _aligned_pair(
    left: list[_Observation], right: list[_Observation], *, kind: str
) -> tuple[_Observation, _Observation] | None:
    if kind == "ttm":
        left_values = [value for value in (_ttm(left),) if value]
        right_values = [value for value in (_ttm(right),) if value]
    elif kind == "annual":
        left_values = _annual(left)
        right_values = _annual(right)
    elif kind == "quarter":
        left_values = _quarters(left)
        right_values = _quarters(right)
    elif kind == "ytd":
        left_values = _ytd(left)
        right_values = _ytd(right)
    else:
        raise ValueError(f"Unsupported aligned period kind: {kind}")
    right_by_end = {value.end_date: value for value in right_values}
    for left_value in reversed(left_values):
        right_value = right_by_end.get(left_value.end_date)
        if right_value and left_value.start_date == right_value.start_date:
            return left_value, right_value
    return None


def _ratio_metric(
    name: str,
    kind: str,
    numerator: _Observation | None,
    denominator: _Observation | None,
) -> SecFinancialMetric:
    if not numerator or not denominator:
        return _missing(name, kind, "required numerator or denominator is unavailable")
    if numerator.start_date != denominator.start_date or numerator.end_date != denominator.end_date:
        return _missing(
            name, kind, "numerator and denominator periods are not aligned", quality="invalid"
        )
    facts = numerator.facts + denominator.facts
    if denominator.value <= 0:
        return _metric(
            name,
            kind,
            numerator,
            value=None,
            quality="invalid",
            formula=f"{numerator.canonical_name} / {denominator.canonical_name}",
            reason="denominator must be positive",
            unit="ratio",
            facts=facts,
        )
    return _metric(
        name,
        kind,
        numerator,
        value=numerator.value / denominator.value,
        quality="derived",
        formula=f"{numerator.canonical_name} / {denominator.canonical_name}",
        unit="ratio",
        facts=facts,
    )


def _growth_metric(
    name: str, kind: str, current: _Observation | None, previous: _Observation | None
) -> SecFinancialMetric:
    if not current or not previous:
        return _missing(name, kind, "current and comparable prior periods are required")
    facts = current.facts + previous.facts
    if current.value == 0 or previous.value == 0 or (current.value > 0) != (previous.value > 0):
        return _metric(
            name,
            kind,
            current,
            value=None,
            quality="invalid",
            formula="(current - prior) / abs(prior)",
            reason="growth is not meaningful when a value is zero or crosses zero",
            unit="ratio",
            facts=facts,
        )
    return _metric(
        name,
        kind,
        current,
        value=(current.value - previous.value) / abs(previous.value),
        quality="derived",
        formula="(current - prior) / abs(prior)",
        unit="ratio",
        facts=facts,
    )


def _comparable_previous(
    current: _Observation | None, candidates: list[_Observation]
) -> _Observation | None:
    if not current or current.days is None:
        return None
    matches = [
        value
        for value in candidates
        if value.end_date < current.end_date
        and 330 <= (current.end_date - value.end_date).days <= 385
        and value.days is not None
        and abs(current.days - value.days) <= 14
    ]
    return max(matches, key=lambda value: value.end_date, default=None)


class SecFinancialCalculator:
    def __init__(self, *, formula_version: str = FORMULA_VERSION):
        self.formula_version = formula_version

    def build_snapshot(
        self,
        *,
        ticker: str,
        company_name: str,
        sector: str,
        facts: tuple[SecCompanyFact, ...],
        as_of: datetime,
    ) -> SecFinancialSnapshot:
        if as_of.tzinfo is None:
            raise ValueError("Financial snapshot as_of must include a timezone")
        effective = SecCompanyFacts.effective_facts(facts, available_at=as_of)
        by_concept: dict[str, list[_Observation]] = defaultdict(list)
        for fact in effective:
            by_concept[fact.canonical_name].append(_reported(fact))

        metrics: list[SecFinancialMetric] = []
        for concept in DURATION_CONCEPTS:
            observations = by_concept[concept]
            period_values = {
                "annual": _latest(_annual(observations)),
                "quarter": _latest(_quarters(observations)),
                "ytd": _latest(_ytd(observations)),
                "ttm": _ttm(observations),
            }
            for period_kind, observation in period_values.items():
                metrics.append(
                    _metric(concept, period_kind, observation)
                    if observation
                    else _missing(concept, period_kind, f"no valid {period_kind} period")
                )

        for concept in INSTANT_CONCEPTS:
            observation = _latest(by_concept[concept])
            metrics.append(
                _metric(concept, "instant", observation)
                if observation
                else _missing(concept, "instant", "no reported instant fact")
            )

        for concept, output_name in (
            ("revenue", "revenue_growth"),
            ("net_income", "earnings_growth"),
        ):
            annuals = _annual(by_concept[concept])
            current_annual = _latest(annuals)
            metrics.append(
                _growth_metric(
                    output_name,
                    "annual",
                    current_annual,
                    _comparable_previous(current_annual, annuals),
                )
            )
            quarters = _quarters(by_concept[concept])
            current_quarter = _latest(quarters)
            metrics.append(
                _growth_metric(
                    output_name,
                    "quarter",
                    current_quarter,
                    _comparable_previous(current_quarter, quarters),
                )
            )

        for period_kind in ("annual", "quarter", "ytd", "ttm"):
            pair = _aligned_pair(
                by_concept["operating_cash_flow"],
                by_concept["capital_expenditures"],
                kind=period_kind,
            )
            if not pair:
                metrics.append(
                    _missing(
                        "free_cash_flow",
                        period_kind,
                        "aligned operating cash flow and capital expenditures are required",
                    )
                )
                continue
            operating_cash_flow, capital_expenditures = pair
            facts_used = operating_cash_flow.facts + capital_expenditures.facts
            if capital_expenditures.value < 0:
                metrics.append(
                    _metric(
                        "free_cash_flow",
                        period_kind,
                        operating_cash_flow,
                        value=None,
                        quality="invalid",
                        formula="operating cash flow - capital expenditures",
                        reason="capital-expenditure payment fact must be nonnegative",
                        facts=facts_used,
                    )
                )
            else:
                metrics.append(
                    _metric(
                        "free_cash_flow",
                        period_kind,
                        operating_cash_flow,
                        value=operating_cash_flow.value - capital_expenditures.value,
                        quality="derived",
                        formula="operating cash flow - capital expenditures",
                        facts=facts_used,
                    )
                )

        for period_kind in ("annual", "quarter", "ytd", "ttm"):
            revenue = self._period_value(by_concept["revenue"], period_kind)
            for numerator_name, metric_name in (
                ("gross_profit", "gross_margin"),
                ("operating_income", "operating_margin"),
                ("net_income", "net_margin"),
            ):
                numerator = self._period_value(by_concept[numerator_name], period_kind)
                metrics.append(_ratio_metric(metric_name, period_kind, numerator, revenue))
            free_cash_flow = next(
                metric
                for metric in metrics
                if metric.metric_name == "free_cash_flow" and metric.period_kind == period_kind
            )
            if free_cash_flow.value is None or revenue is None:
                metrics.append(
                    _missing(
                        "free_cash_flow_margin",
                        period_kind,
                        "valid free cash flow and revenue are required",
                    )
                )
            else:
                cash_flow_pair = _aligned_pair(
                    by_concept["operating_cash_flow"],
                    by_concept["capital_expenditures"],
                    kind=period_kind,
                )
                assert cash_flow_pair is not None
                fcf_observation = _Observation(
                    canonical_name="free_cash_flow",
                    value=free_cash_flow.value,
                    unit=free_cash_flow.unit,
                    start_date=free_cash_flow.start_date,
                    end_date=free_cash_flow.end_date or revenue.end_date,
                    fiscal_year=free_cash_flow.fiscal_year,
                    fiscal_period=free_cash_flow.fiscal_period,
                    quality=free_cash_flow.quality,
                    formula=free_cash_flow.formula,
                    facts=cash_flow_pair[0].facts + cash_flow_pair[1].facts,
                )
                metrics.append(
                    _ratio_metric("free_cash_flow_margin", period_kind, fcf_observation, revenue)
                )

        metrics.append(self._current_ratio(by_concept))
        metrics.append(self._return_on_equity(by_concept))
        metrics = self._apply_sector_exclusions(metrics, sector)
        usable = sum(metric.value is not None for metric in metrics)
        warnings = tuple(
            sorted(
                {
                    metric.reason
                    for metric in metrics
                    if metric.quality == "invalid" and metric.reason
                }
            )
        )
        return SecFinancialSnapshot(
            snapshot_id=uuid4().hex,
            ticker=ticker,
            company_name=company_name,
            sector=sector,
            as_of=as_of.astimezone(UTC),
            built_at=datetime.now(UTC),
            formula_version=self.formula_version,
            status="complete" if usable else "insufficient_data",
            warnings=warnings,
            metrics=tuple(metrics),
        )

    @staticmethod
    def _period_value(observations: list[_Observation], period_kind: str) -> _Observation | None:
        if period_kind == "annual":
            return _latest(_annual(observations))
        if period_kind == "quarter":
            return _latest(_quarters(observations))
        if period_kind == "ytd":
            return _latest(_ytd(observations))
        if period_kind == "ttm":
            return _ttm(observations)
        raise ValueError(f"Unsupported period kind: {period_kind}")

    @staticmethod
    def _current_ratio(
        by_concept: dict[str, list[_Observation]],
    ) -> SecFinancialMetric:
        assets_by_end = {value.end_date: value for value in by_concept["current_assets"]}
        liabilities_by_end = {value.end_date: value for value in by_concept["current_liabilities"]}
        common_dates = sorted(set(assets_by_end) & set(liabilities_by_end))
        if not common_dates:
            return _missing(
                "current_ratio", "instant", "aligned current assets and liabilities are required"
            )
        end_date = common_dates[-1]
        return _ratio_metric(
            "current_ratio",
            "instant",
            assets_by_end[end_date],
            liabilities_by_end[end_date],
        )

    @staticmethod
    def _return_on_equity(
        by_concept: dict[str, list[_Observation]],
    ) -> SecFinancialMetric:
        income = _ttm(by_concept["net_income"])
        if not income or not income.start_date:
            return _missing("return_on_equity", "ttm", "valid TTM net income is required")
        equity = by_concept["stockholders_equity"]
        ending = min(
            equity,
            key=lambda item: abs((item.end_date - income.end_date).days),
            default=None,
        )
        target_start = income.start_date - timedelta(days=1)
        beginning = min(
            equity,
            key=lambda item: abs((item.end_date - target_start).days),
            default=None,
        )
        if (
            not beginning
            or not ending
            or abs((ending.end_date - income.end_date).days) > 14
            or abs((beginning.end_date - target_start).days) > 14
        ):
            return _missing(
                "return_on_equity",
                "ttm",
                "beginning and ending equity aligned to the TTM period are required",
            )
        average_equity = (beginning.value + ending.value) / Decimal(2)
        facts = income.facts + beginning.facts + ending.facts
        if average_equity <= 0:
            return _metric(
                "return_on_equity",
                "ttm",
                income,
                value=None,
                quality="invalid",
                formula="TTM net income / average beginning and ending equity",
                reason="average equity must be positive",
                unit="ratio",
                facts=facts,
            )
        return _metric(
            "return_on_equity",
            "ttm",
            income,
            value=income.value / average_equity,
            quality="derived",
            formula="TTM net income / average beginning and ending equity",
            unit="ratio",
            facts=facts,
        )

    @staticmethod
    def _apply_sector_exclusions(
        metrics: list[SecFinancialMetric], sector: str
    ) -> list[SecFinancialMetric]:
        if sector != "Financials":
            return metrics
        output: list[SecFinancialMetric] = []
        for metric in metrics:
            if metric.metric_name not in FINANCIAL_SECTOR_EXCLUSIONS:
                output.append(metric)
                continue
            output.append(
                SecFinancialMetric(
                    metric_name=metric.metric_name,
                    period_kind=metric.period_kind,
                    value=None,
                    unit=metric.unit,
                    start_date=metric.start_date,
                    end_date=metric.end_date,
                    fiscal_year=metric.fiscal_year,
                    fiscal_period=metric.fiscal_period,
                    quality="excluded",
                    formula=metric.formula,
                    reason="excluded for Financials because the industrial ratio is not comparable",
                    lineage=metric.lineage,
                )
            )
        return output
