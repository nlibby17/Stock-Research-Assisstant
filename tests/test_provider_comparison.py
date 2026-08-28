from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from stockrank.models import (
    FundamentalSnapshot,
    ProviderComparisonRun,
    SecFinancialMetric,
    SecFinancialSnapshot,
)
from stockrank.provider_comparison import (
    ProviderComparisonConfig,
    ProviderComparisonSpec,
    compare_provider_metrics,
    load_provider_comparison_config,
)
from stockrank.storage import Storage

AS_OF = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def spec(
    *,
    basis: str = "comparable",
    name: str = "total_revenue",
    yahoo_field: str = "total_revenue",
    sec_metric: str | None = "revenue",
    sec_period: str | None = "ttm",
) -> ProviderComparisonSpec:
    return ProviderComparisonSpec(
        name=name,
        yahoo_field=yahoo_field,
        sec_metric=sec_metric,
        sec_period=sec_period,
        comparison_basis=basis,
        period_alignment="test alignment",
        sec_max_period_age_days=190,
        strict_absolute_tolerance=Decimal(2),
        strict_relative_tolerance=Decimal("0.02"),
        material_absolute_tolerance=Decimal(20),
        material_relative_tolerance=Decimal("0.20"),
    )


def config(*specs: ProviderComparisonSpec) -> ProviderComparisonConfig:
    return ProviderComparisonConfig(
        version="test-v1",
        required_full_universe_dates=3,
        yahoo_max_age_hours=Decimal(72),
        metrics=specs or (spec(),),
    )


def sec_metric(
    value: str | None = "100",
    *,
    quality: str = "derived",
    reason: str | None = None,
    end_date: date = date(2026, 6, 30),
) -> SecFinancialMetric:
    return SecFinancialMetric(
        metric_name="revenue",
        period_kind="ttm",
        value=Decimal(value) if value is not None else None,
        unit="USD",
        start_date=date(2025, 7, 1),
        end_date=end_date,
        fiscal_year=2026,
        fiscal_period="TTM",
        quality=quality,
        formula="sum quarters",
        reason=reason,
        lineage=(),
    )


def sec_snapshot(metric: SecFinancialMetric | None = None) -> SecFinancialSnapshot:
    return SecFinancialSnapshot(
        snapshot_id="sec-snapshot-1",
        ticker="TEST",
        company_name="Test Company",
        sector="Industrials",
        as_of=AS_OF - timedelta(hours=2),
        built_at=AS_OF - timedelta(hours=2),
        formula_version="sec-v1",
        status="complete",
        warnings=(),
        metrics=(metric or sec_metric(),),
    )


def yahoo(value: float | None = 101.0, *, age_hours: int = 1) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        ticker="TEST",
        source="yfinance",
        fetched_at=AS_OF - timedelta(hours=age_hours),
        total_revenue=value,
    )


def compare(
    comparison_config: ProviderComparisonConfig,
    *,
    sec: SecFinancialSnapshot | None = None,
    fundamental: FundamentalSnapshot | None = None,
):
    return compare_provider_metrics(
        comparison_run_id="comparison-1",
        ticker="TEST",
        sector="Industrials",
        as_of=AS_OF,
        config=comparison_config,
        sec_snapshot=sec if sec is not None else sec_snapshot(),
        yahoo_fundamental=fundamental if fundamental is not None else yahoo(),
    )[0]


def test_strict_tolerance_and_approximate_basis_classifications():
    direct = compare(config(spec()))
    assert direct.classification == "comparable"
    assert direct.absolute_difference == Decimal(1)
    assert direct.relative_difference == Decimal(1) / Decimal(101)

    approximate = compare(config(spec(basis="approximately_comparable")))
    assert approximate.classification == "approximately_comparable"
    assert approximate.period_alignment == "test alignment"


def test_material_difference_requires_both_material_thresholds():
    material = compare(config(spec()), fundamental=yahoo(200))
    assert material.classification == "materially_different"
    assert material.absolute_difference == Decimal(100)
    assert material.relative_difference == Decimal("0.5")

    moderate = compare(config(spec()), fundamental=yahoo(115))
    assert moderate.classification == "approximately_comparable"


def test_stale_missing_and_fallback_states_are_explicit():
    stale = compare(config(spec()), fundamental=yahoo(101, age_hours=100))
    assert stale.classification == "stale"
    assert stale.fallback_candidate == "sec_fresher_than_yahoo"

    yahoo_missing = compare(config(spec()), fundamental=yahoo(None))
    assert yahoo_missing.classification == "missing"
    assert yahoo_missing.fallback_candidate == "sec_available_for_yahoo_gap"

    invalid_sec = sec_snapshot(
        sec_metric(None, quality="invalid", reason="denominator must be positive")
    )
    sec_missing = compare(config(spec()), sec=invalid_sec, fundamental=yahoo(101))
    assert sec_missing.classification == "missing"
    assert sec_missing.fallback_candidate == "yahoo_available_for_sec_gap"
    assert "denominator" in sec_missing.reason


def test_structural_mapping_and_sector_exclusion_are_not_fallbacks():
    structural_spec = spec(
        basis="structurally_incomparable",
        name="debt_to_equity",
        yahoo_field="debt_to_equity",
        sec_metric=None,
        sec_period=None,
    )
    fundamental = yahoo()
    fundamental.debt_to_equity = 120.0
    structural = compare(config(structural_spec), fundamental=fundamental)
    assert structural.classification == "structurally_incomparable"
    assert structural.fallback_candidate is None

    excluded = sec_snapshot(
        sec_metric(None, quality="excluded", reason="industrial ratio excluded")
    )
    comparison = compare(config(spec()), sec=excluded)
    assert comparison.classification == "structurally_incomparable"


def test_virtual_yahoo_fcf_margin_is_compared():
    margin_spec = spec(
        basis="approximately_comparable",
        name="free_cash_flow_margin",
        yahoo_field="free_cash_flow_margin",
        sec_metric="free_cash_flow_margin",
    )
    sec_value = replace(sec_metric("0.2"), metric_name="free_cash_flow_margin", unit="ratio")
    fundamental = yahoo(None)
    fundamental.free_cash_flow = 20
    fundamental.total_revenue = 100
    comparison = compare(
        config(margin_spec), sec=sec_snapshot(sec_value), fundamental=fundamental
    )
    assert comparison.yahoo_value == Decimal("0.2")
    assert comparison.classification == "approximately_comparable"


def test_real_comparison_config_is_valid():
    from stockrank.config import load_settings

    project_root = Path(__file__).resolve().parents[1]
    loaded = load_provider_comparison_config(load_settings(project_root))
    assert loaded.version == "provider-shadow-v1.0.1"
    assert loaded.required_full_universe_dates == 3
    assert {value.name for value in loaded.metrics} >= {
        "total_revenue",
        "free_cash_flow_margin",
        "debt_to_equity",
    }


def test_comparison_storage_roundtrip_progress_and_immutability(tmp_path):
    storage = Storage(tmp_path / "comparison.sqlite3")
    storage.initialize()
    comparison = compare(config(spec()))
    run = ProviderComparisonRun(
        comparison_run_id="comparison-1",
        started_at=AS_OF,
        completed_at=AS_OF + timedelta(seconds=1),
        as_of=AS_OF,
        config_version="test-v1",
        universe_name="test-universe",
        scope_count=1,
        universe_size=1,
        full_universe=True,
        status="complete",
        warnings=(),
        analysis_run_id="analysis-1",
        evidence_date=date(2026, 8, 27),
        evidence_qualified=True,
        evidence_reason="Qualified test evidence",
    )
    assert storage.save_provider_comparison_run(run, (comparison,)) == 1
    loaded_run = storage.latest_provider_comparison_run(full_universe_only=True)
    assert loaded_run == run
    loaded = storage.get_provider_metric_comparisons("comparison-1")
    assert loaded == [comparison]
    assert (
        storage.provider_comparison_full_universe_dates(
            "test-v1", "America/New_York"
        )
        == 1
    )
    with pytest.raises(ValueError, match="already exists"):
        storage.save_provider_comparison_run(run, (comparison,))

    same_day_run = replace(
        run,
        comparison_run_id="comparison-2",
        as_of=AS_OF + timedelta(hours=13),
        completed_at=AS_OF + timedelta(hours=13, seconds=1),
    )
    same_day_comparison = replace(
        comparison, comparison_run_id=same_day_run.comparison_run_id
    )
    storage.save_provider_comparison_run(same_day_run, (same_day_comparison,))
    assert storage.provider_comparison_full_universe_dates("test-v1") == 1
    assert (
        storage.provider_comparison_full_universe_dates(
            "test-v1", "America/New_York"
        )
        == 1
    )

    next_day_run = replace(
        run,
        comparison_run_id="comparison-3",
        as_of=AS_OF + timedelta(days=1),
        completed_at=AS_OF + timedelta(days=1, seconds=1),
        evidence_date=date(2026, 8, 28),
    )
    next_day_comparison = replace(
        comparison, comparison_run_id=next_day_run.comparison_run_id
    )
    storage.save_provider_comparison_run(next_day_run, (next_day_comparison,))
    assert (
        storage.provider_comparison_full_universe_dates(
            "test-v1", "America/New_York"
        )
        == 2
    )

    unqualified_run = replace(
        run,
        comparison_run_id="comparison-4",
        evidence_date=date(2026, 8, 29),
        evidence_qualified=False,
        evidence_reason="Mixed market-data dates",
    )
    unqualified_comparison = replace(
        comparison, comparison_run_id=unqualified_run.comparison_run_id
    )
    storage.save_provider_comparison_run(unqualified_run, (unqualified_comparison,))
    assert storage.provider_comparison_full_universe_dates("test-v1") == 2
