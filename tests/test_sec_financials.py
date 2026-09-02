from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stockrank.cli import _financial_as_of
from stockrank.models import SecCompanyFact
from stockrank.sec_financials import FORMULA_VERSION, SecFinancialCalculator, formula_manifest
from stockrank.storage import Storage


def fact(
    canonical_name: str,
    value: str | int,
    start: date | None,
    end: date,
    *,
    fiscal_period: str,
    accession_suffix: int,
    accepted_at: datetime | None = None,
) -> SecCompanyFact:
    accepted = accepted_at or datetime(2025, 6, 1, 20, 0, tzinfo=UTC)
    period_type = "duration" if start else "instant"
    unit = "shares" if "shares" in canonical_name else "USD"
    return SecCompanyFact(
        cik="0000000001",
        ticker="TEST",
        company_name="Test Company",
        canonical_name=canonical_name,
        taxonomy="us-gaap",
        concept=canonical_name.title().replace("_", ""),
        concept_priority=0,
        label=canonical_name,
        description=f"Test {canonical_name}",
        period_type=period_type,
        unit=unit,
        value=Decimal(value),
        start_date=start,
        end_date=end,
        accession_number=f"0000000001-25-{accession_suffix:06d}",
        fiscal_year=end.year,
        fiscal_period=fiscal_period,
        form="10-K" if fiscal_period == "FY" else "10-Q",
        filed_date=accepted.date(),
        frame=None,
        accepted_at=accepted,
        availability_date=accepted.date(),
        availability_precision="timestamp",
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def cumulative_sequence(
    canonical_name: str,
    values: tuple[int, int, int, int, int],
    *,
    accession_offset: int,
) -> list[SecCompanyFact]:
    periods = (
        (date(2024, 2, 1), date(2024, 4, 30), "Q1"),
        (date(2024, 2, 1), date(2024, 7, 31), "Q2"),
        (date(2024, 2, 1), date(2024, 10, 31), "Q3"),
        (date(2024, 2, 1), date(2025, 1, 31), "FY"),
        (date(2025, 2, 1), date(2025, 4, 30), "Q1"),
    )
    return [
        fact(
            canonical_name,
            value,
            start,
            end,
            fiscal_period=fiscal_period,
            accession_suffix=accession_offset + index,
        )
        for index, (value, (start, end, fiscal_period)) in enumerate(zip(values, periods))
    ]


def full_fact_set() -> tuple[SecCompanyFact, ...]:
    values: list[SecCompanyFact] = []
    sequences = (
        ("revenue", (100, 220, 360, 520, 180)),
        ("net_income", (10, 25, 45, 70, 20)),
        ("gross_profit", (40, 90, 150, 220, 72)),
        ("operating_income", (15, 35, 60, 90, 27)),
        ("operating_cash_flow", (20, 50, 80, 120, 40)),
        ("capital_expenditures", (5, 12, 20, 30, 8)),
        ("weighted_average_diluted_shares", (100, 110, 120, 130, 140)),
    )
    for offset, (canonical_name, sequence) in enumerate(sequences, start=1):
        values.extend(
            cumulative_sequence(
                canonical_name,
                sequence,
                accession_offset=offset * 100,
            )
        )
    values.extend(
        [
            fact(
                "revenue",
                400,
                date(2023, 2, 1),
                date(2024, 1, 31),
                fiscal_period="FY",
                accession_suffix=800,
            ),
            fact(
                "net_income",
                50,
                date(2023, 2, 1),
                date(2024, 1, 31),
                fiscal_period="FY",
                accession_suffix=801,
            ),
            fact(
                "stockholders_equity",
                200,
                None,
                date(2024, 4, 30),
                fiscal_period="Q1",
                accession_suffix=802,
            ),
            fact(
                "stockholders_equity",
                300,
                None,
                date(2025, 4, 30),
                fiscal_period="Q1",
                accession_suffix=803,
            ),
            fact(
                "current_assets",
                500,
                None,
                date(2025, 4, 30),
                fiscal_period="Q1",
                accession_suffix=804,
            ),
            fact(
                "current_liabilities",
                250,
                None,
                date(2025, 4, 30),
                fiscal_period="Q1",
                accession_suffix=805,
            ),
        ]
    )
    return tuple(values)


def metric(snapshot, name: str, period: str):
    return next(
        value
        for value in snapshot.metrics
        if value.metric_name == name and value.period_kind == period
    )


def build(facts: tuple[SecCompanyFact, ...], sector: str = "Industrials"):
    return SecFinancialCalculator().build_snapshot(
        ticker="TEST",
        company_name="Test Company",
        sector=sector,
        facts=facts,
        as_of=datetime(2025, 12, 31, 23, 59, tzinfo=UTC),
    )


def test_noncalendar_cumulative_quarters_ttm_growth_and_ratios():
    snapshot = build(full_fact_set())

    assert metric(snapshot, "revenue", "annual").value == Decimal(520)
    assert metric(snapshot, "revenue", "quarter").value == Decimal(180)
    assert metric(snapshot, "revenue", "ttm").value == Decimal(600)
    assert metric(snapshot, "revenue", "ttm").start_date == date(2024, 5, 1)
    assert metric(snapshot, "revenue_growth", "annual").value == Decimal("0.3")
    assert metric(snapshot, "revenue_growth", "quarter").value == Decimal("0.8")
    assert metric(snapshot, "free_cash_flow", "ttm").value == Decimal(107)
    assert metric(snapshot, "gross_margin", "ttm").value == Decimal("0.42")
    assert metric(snapshot, "net_margin", "ttm").value == Decimal(80) / Decimal(600)
    assert metric(snapshot, "current_ratio", "instant").value == Decimal(2)
    assert metric(snapshot, "return_on_equity", "ttm").value == Decimal("0.32")
    weighted_shares = metric(snapshot, "weighted_average_diluted_shares", "ttm")
    assert Decimal(100) < weighted_shares.value < Decimal(170)
    assert "day-weighted average" in weighted_shares.formula
    assert metric(snapshot, "revenue", "ttm").quality == "derived"
    # Four derived quarters require five cumulative source contexts.
    assert len(metric(snapshot, "revenue", "ttm").lineage) == 5


def test_53_week_annual_period_is_accepted_without_calendar_year_assumptions():
    annual = fact(
        "revenue",
        100,
        date(2024, 1, 28),
        date(2025, 2, 1),
        fiscal_period="FY",
        accession_suffix=999,
    )
    value = metric(build((annual,)), "revenue", "annual")
    assert value.value == Decimal(100)
    assert (value.end_date - value.start_date).days + 1 == 371


def test_point_in_time_cutoff_selects_later_restatement_only_when_available():
    original = fact(
        "revenue",
        100,
        date(2024, 1, 1),
        date(2024, 12, 31),
        fiscal_period="FY",
        accession_suffix=1,
        accepted_at=datetime(2025, 2, 1, tzinfo=UTC),
    )
    restated = replace(
        original,
        value=Decimal(120),
        accession_number="0000000001-26-000002",
        accepted_at=datetime(2026, 2, 1, tzinfo=UTC),
        availability_date=date(2026, 2, 1),
        filed_date=date(2026, 2, 1),
    )
    calculator = SecFinancialCalculator()
    before = calculator.build_snapshot(
        ticker="TEST",
        company_name="Test Company",
        sector="Industrials",
        facts=(original, restated),
        as_of=datetime(2025, 12, 31, tzinfo=UTC),
    )
    after = calculator.build_snapshot(
        ticker="TEST",
        company_name="Test Company",
        sector="Industrials",
        facts=(original, restated),
        as_of=datetime(2026, 12, 31, tzinfo=UTC),
    )
    assert metric(before, "revenue", "annual").value == Decimal(100)
    assert metric(after, "revenue", "annual").value == Decimal(120)


def test_growth_zero_and_sign_crossings_are_invalid_not_extreme_percentages():
    facts = (
        fact(
            "net_income",
            -10,
            date(2023, 1, 1),
            date(2023, 12, 31),
            fiscal_period="FY",
            accession_suffix=1,
        ),
        fact(
            "net_income",
            5,
            date(2024, 1, 1),
            date(2024, 12, 31),
            fiscal_period="FY",
            accession_suffix=2,
        ),
    )
    value = metric(build(facts), "earnings_growth", "annual")
    assert value.value is None
    assert value.quality == "invalid"
    assert "crosses zero" in value.reason


def test_missing_inputs_remain_missing_and_financial_sector_rules_are_explicit():
    sparse = build((full_fact_set()[0],))
    assert metric(sparse, "free_cash_flow", "ttm").value is None
    assert metric(sparse, "free_cash_flow", "ttm").quality == "missing"

    financial = build(full_fact_set(), sector="Financials")
    excluded = metric(financial, "free_cash_flow_margin", "ttm")
    assert excluded.value is None
    assert excluded.quality == "excluded"
    assert "Financials" in excluded.reason
    assert metric(financial, "return_on_equity", "ttm").value == Decimal("0.32")


def test_snapshot_storage_is_exact_and_immutable(tmp_path):
    storage = Storage(tmp_path / "financials.sqlite3")
    storage.initialize()
    snapshot = build(full_fact_set())
    assert storage.save_sec_financial_snapshot(snapshot) == len(snapshot.metrics)

    loaded = storage.latest_sec_financial_snapshot("TEST")
    assert loaded is not None
    assert loaded.snapshot_id == snapshot.snapshot_id
    assert loaded.formula_version == FORMULA_VERSION
    assert loaded.formula_manifest == formula_manifest()
    assert loaded.formula_manifest["fingerprint"]
    assert metric(loaded, "free_cash_flow", "ttm").value == Decimal(107)
    assert metric(loaded, "free_cash_flow", "ttm").lineage
    with pytest.raises(ValueError, match="already exists"):
        storage.save_sec_financial_snapshot(snapshot)

    later = replace(
        snapshot,
        snapshot_id="later-snapshot",
        as_of=snapshot.as_of + timedelta(days=1),
        built_at=snapshot.built_at + timedelta(days=1),
    )
    storage.save_sec_financial_snapshot(later)
    cutoff = storage.latest_sec_financial_snapshot("TEST", available_at=snapshot.as_of)
    assert cutoff is not None
    assert cutoff.snapshot_id == snapshot.snapshot_id

    late_build_of_older_data = replace(
        snapshot,
        snapshot_id="late-build-of-older-data",
        as_of=snapshot.as_of - timedelta(hours=1),
        built_at=snapshot.built_at + timedelta(days=2),
    )
    storage.save_sec_financial_snapshot(late_build_of_older_data)
    cutoff = storage.latest_sec_financial_snapshot(
        "TEST",
        available_at=snapshot.built_at,
        built_at_or_before=snapshot.built_at,
    )
    assert cutoff is not None
    assert cutoff.snapshot_id == snapshot.snapshot_id
    with pytest.raises(ValueError, match="build cutoff must include a timezone"):
        storage.latest_sec_financial_snapshot(
            "TEST",
            built_at_or_before=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
        )


def test_date_only_cutoff_uses_end_of_configured_local_day():
    value = _financial_as_of("2026-08-26", "America/New_York")
    assert value == datetime(2026, 8, 27, 3, 59, 59, 999999, tzinfo=UTC)
