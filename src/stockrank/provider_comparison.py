from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from stockrank.models import (
    FundamentalSnapshot,
    ProviderMetricComparison,
    SecFinancialMetric,
    SecFinancialSnapshot,
)

if TYPE_CHECKING:
    from stockrank.config import Settings


VALID_BASES = frozenset(
    {"comparable", "approximately_comparable", "structurally_incomparable"}
)


@dataclass(frozen=True)
class ProviderComparisonSpec:
    name: str
    yahoo_field: str
    sec_metric: str | None
    sec_period: str | None
    comparison_basis: str
    period_alignment: str
    sec_max_period_age_days: int
    strict_absolute_tolerance: Decimal
    strict_relative_tolerance: Decimal
    material_absolute_tolerance: Decimal
    material_relative_tolerance: Decimal


@dataclass(frozen=True)
class ProviderComparisonConfig:
    version: str
    required_full_universe_dates: int
    yahoo_max_age_hours: Decimal
    metrics: tuple[ProviderComparisonSpec, ...]


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal for {field}: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Non-finite decimal for {field}: {value!r}")
    return result


def load_provider_comparison_config(settings: Settings) -> ProviderComparisonConfig:
    configured = settings.raw.get("provider_comparison", {}).get(
        "path", "config/provider_comparison.toml"
    )
    path = Path(str(configured))
    if not path.is_absolute():
        path = settings.root / path
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except OSError as exc:
        raise ValueError(f"Unable to read provider comparison config {path}: {exc}") from exc
    comparison = payload.get("comparison", {})
    version = str(comparison.get("version", "")).strip()
    required_dates = int(comparison.get("required_full_universe_dates", 0))
    yahoo_max_age = _decimal(
        comparison.get("yahoo_max_age_hours"), field="comparison.yahoo_max_age_hours"
    )
    if not version or required_dates < 1 or yahoo_max_age <= 0:
        raise ValueError("Provider comparison metadata is incomplete or invalid")
    specs: list[ProviderComparisonSpec] = []
    for index, raw in enumerate(payload.get("metrics", ())):
        name = str(raw.get("name", "")).strip()
        yahoo_field = str(raw.get("yahoo_field", "")).strip()
        basis = str(raw.get("comparison_basis", "")).strip()
        sec_metric = str(raw.get("sec_metric", "")).strip() or None
        sec_period = str(raw.get("sec_period", "")).strip() or None
        if not name or not yahoo_field or basis not in VALID_BASES:
            raise ValueError(f"Invalid provider comparison metric at index {index}")
        if basis != "structurally_incomparable" and (not sec_metric or not sec_period):
            raise ValueError(f"Comparable metric {name} requires an SEC metric and period")
        spec = ProviderComparisonSpec(
            name=name,
            yahoo_field=yahoo_field,
            sec_metric=sec_metric,
            sec_period=sec_period,
            comparison_basis=basis,
            period_alignment=str(raw.get("period_alignment", "")).strip(),
            sec_max_period_age_days=int(raw.get("sec_max_period_age_days", 0)),
            strict_absolute_tolerance=_decimal(
                raw.get("strict_absolute_tolerance"),
                field=f"metrics.{name}.strict_absolute_tolerance",
            ),
            strict_relative_tolerance=_decimal(
                raw.get("strict_relative_tolerance"),
                field=f"metrics.{name}.strict_relative_tolerance",
            ),
            material_absolute_tolerance=_decimal(
                raw.get("material_absolute_tolerance"),
                field=f"metrics.{name}.material_absolute_tolerance",
            ),
            material_relative_tolerance=_decimal(
                raw.get("material_relative_tolerance"),
                field=f"metrics.{name}.material_relative_tolerance",
            ),
        )
        tolerances = (
            spec.strict_absolute_tolerance,
            spec.strict_relative_tolerance,
            spec.material_absolute_tolerance,
            spec.material_relative_tolerance,
        )
        if spec.sec_max_period_age_days <= 0 or any(value < 0 for value in tolerances):
            raise ValueError(f"Metric {name} has invalid age or tolerance values")
        if (
            spec.material_absolute_tolerance < spec.strict_absolute_tolerance
            or spec.material_relative_tolerance < spec.strict_relative_tolerance
        ):
            raise ValueError(f"Metric {name} material tolerances must not be stricter")
        specs.append(spec)
    if not specs or len({spec.name for spec in specs}) != len(specs):
        raise ValueError("Provider comparison metrics must be nonempty and unique")
    return ProviderComparisonConfig(
        version=version,
        required_full_universe_dates=required_dates,
        yahoo_max_age_hours=yahoo_max_age,
        metrics=tuple(specs),
    )


def _yahoo_value(
    fundamental: FundamentalSnapshot | None, field: str
) -> Decimal | None:
    if not fundamental:
        return None
    if field == "free_cash_flow_margin":
        if (
            fundamental.free_cash_flow is None
            or fundamental.total_revenue is None
            or fundamental.total_revenue <= 0
        ):
            return None
        value = fundamental.free_cash_flow / fundamental.total_revenue
    else:
        value = getattr(fundamental, field, None)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return Decimal(str(number)) if math.isfinite(number) else None


def _sec_metric(
    snapshot: SecFinancialSnapshot | None, spec: ProviderComparisonSpec
) -> SecFinancialMetric | None:
    if not snapshot or not spec.sec_metric or not spec.sec_period:
        return None
    return next(
        (
            metric
            for metric in snapshot.metrics
            if metric.metric_name == spec.sec_metric
            and metric.period_kind == spec.sec_period
        ),
        None,
    )


def _relative_difference(left: Decimal, right: Decimal) -> Decimal:
    denominator = max(abs(left), abs(right))
    return Decimal(0) if denominator == 0 else abs(left - right) / denominator


def compare_provider_metrics(
    *,
    comparison_run_id: str,
    ticker: str,
    sector: str,
    as_of: datetime,
    config: ProviderComparisonConfig,
    sec_snapshot: SecFinancialSnapshot | None,
    yahoo_fundamental: FundamentalSnapshot | None,
) -> tuple[ProviderMetricComparison, ...]:
    if as_of.tzinfo is None:
        raise ValueError("Provider comparison as_of must include a timezone")
    as_of = as_of.astimezone(UTC)
    yahoo_fetched = yahoo_fundamental.fetched_at if yahoo_fundamental else None
    if yahoo_fetched and yahoo_fetched.tzinfo is None:
        raise ValueError("Yahoo fundamental fetched_at must include a timezone")
    yahoo_age = (
        Decimal(str((as_of - yahoo_fetched.astimezone(UTC)).total_seconds())) / Decimal(3600)
        if yahoo_fetched
        else None
    )
    if yahoo_age is not None and yahoo_age < 0:
        raise ValueError("Yahoo fundamental snapshot is newer than the comparison cutoff")

    output: list[ProviderMetricComparison] = []
    for spec in config.metrics:
        yahoo_value = _yahoo_value(yahoo_fundamental, spec.yahoo_field)
        sec_metric = _sec_metric(sec_snapshot, spec)
        sec_value = sec_metric.value if sec_metric and sec_metric.value is not None else None
        sec_age = (
            (as_of.date() - sec_metric.end_date).days
            if sec_metric and sec_metric.end_date
            else None
        )
        if sec_age is not None and sec_age < 0:
            raise ValueError(f"SEC metric {spec.name} ends after the comparison cutoff")
        absolute_difference = (
            abs(sec_value - yahoo_value)
            if sec_value is not None and yahoo_value is not None
            else None
        )
        relative_difference = (
            _relative_difference(sec_value, yahoo_value)
            if sec_value is not None and yahoo_value is not None
            else None
        )
        classification, fallback, reason = _classify(
            spec=spec,
            sec_metric=sec_metric,
            sec_value=sec_value,
            sec_age_days=sec_age,
            yahoo_value=yahoo_value,
            yahoo_age_hours=yahoo_age,
            yahoo_max_age_hours=config.yahoo_max_age_hours,
            absolute_difference=absolute_difference,
            relative_difference=relative_difference,
        )
        output.append(
            ProviderMetricComparison(
                comparison_run_id=comparison_run_id,
                ticker=ticker,
                sector=sector,
                metric_name=spec.name,
                yahoo_field=spec.yahoo_field,
                yahoo_value=yahoo_value,
                yahoo_fetched_at=yahoo_fetched,
                yahoo_age_hours=yahoo_age,
                sec_metric_name=spec.sec_metric,
                sec_period_kind=spec.sec_period,
                sec_value=sec_value,
                sec_unit=sec_metric.unit if sec_metric else None,
                sec_start_date=sec_metric.start_date if sec_metric else None,
                sec_end_date=sec_metric.end_date if sec_metric else None,
                sec_quality=sec_metric.quality if sec_metric else None,
                sec_snapshot_id=sec_snapshot.snapshot_id if sec_snapshot else None,
                sec_period_age_days=sec_age,
                comparison_basis=spec.comparison_basis,
                period_alignment=spec.period_alignment,
                classification=classification,
                absolute_difference=absolute_difference,
                relative_difference=relative_difference,
                strict_absolute_tolerance=spec.strict_absolute_tolerance,
                strict_relative_tolerance=spec.strict_relative_tolerance,
                material_absolute_tolerance=spec.material_absolute_tolerance,
                material_relative_tolerance=spec.material_relative_tolerance,
                fallback_candidate=fallback,
                reason=reason,
            )
        )
    return tuple(output)


def _classify(
    *,
    spec: ProviderComparisonSpec,
    sec_metric: SecFinancialMetric | None,
    sec_value: Decimal | None,
    sec_age_days: int | None,
    yahoo_value: Decimal | None,
    yahoo_age_hours: Decimal | None,
    yahoo_max_age_hours: Decimal,
    absolute_difference: Decimal | None,
    relative_difference: Decimal | None,
) -> tuple[str, str | None, str]:
    if spec.comparison_basis == "structurally_incomparable":
        return "structurally_incomparable", None, spec.period_alignment
    if sec_metric and sec_metric.quality == "excluded":
        return "structurally_incomparable", None, sec_metric.reason or "SEC metric excluded"
    if sec_value is None or yahoo_value is None:
        missing = []
        if sec_value is None:
            missing.append("SEC")
        if yahoo_value is None:
            missing.append("Yahoo")
        fallback = (
            "sec_available_for_yahoo_gap"
            if sec_value is not None
            else "yahoo_available_for_sec_gap"
            if yahoo_value is not None
            else None
        )
        sec_reason = f"; SEC quality={sec_metric.quality}: {sec_metric.reason}" if sec_metric else ""
        return "missing", fallback, f"Missing {' and '.join(missing)} value{sec_reason}"
    yahoo_stale = yahoo_age_hours is None or yahoo_age_hours > yahoo_max_age_hours
    sec_stale = sec_age_days is None or sec_age_days > spec.sec_max_period_age_days
    if yahoo_stale or sec_stale:
        stale = []
        if yahoo_stale:
            stale.append("Yahoo snapshot")
        if sec_stale:
            stale.append("SEC period")
        fallback = (
            "sec_fresher_than_yahoo"
            if yahoo_stale and not sec_stale
            else "yahoo_fresher_than_sec"
            if sec_stale and not yahoo_stale
            else None
        )
        return "stale", fallback, " and ".join(stale) + " exceeds configured age limit"
    assert absolute_difference is not None and relative_difference is not None
    within_strict = (
        absolute_difference <= spec.strict_absolute_tolerance
        or relative_difference <= spec.strict_relative_tolerance
    )
    if within_strict:
        classification = (
            "comparable"
            if spec.comparison_basis == "comparable"
            else "approximately_comparable"
        )
        return classification, None, "Values are within the configured strict tolerance"
    materially_different = (
        absolute_difference > spec.material_absolute_tolerance
        and relative_difference > spec.material_relative_tolerance
    )
    if materially_different:
        return (
            "materially_different",
            None,
            "Difference exceeds both configured material tolerances",
        )
    return (
        "approximately_comparable",
        None,
        "Difference exceeds strict tolerance but remains below a material threshold",
    )
