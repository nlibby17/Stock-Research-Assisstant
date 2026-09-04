import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stockrank.data.sec import SecCompanyFacts
from stockrank.models import (
    AnalysisRun,
    FundamentalSnapshot,
    PriceBar,
    ProviderHealth,
    ScoredSecurity,
    SecCompanyFact,
    SecCompanyFactsRefreshState,
    SecFiling,
)
from stockrank.reproducibility import RUN_MANIFEST_VERSION, stable_fingerprint
from stockrank.storage import SCHEMA_VERSION, Storage


def run_manifest(universe_name: str, model_version: str, tickers: tuple[str, ...] = ("A",)) -> dict:
    contract = {
        "version": "ranking-calculations-v1",
        "implementation_fingerprint": "implementation",
        "provider_name": "test",
        "provider_policy_fingerprint": "provider-policy",
        "selection_policy_fingerprint": "selection-policy",
        "model_version": model_version,
        "calculation_version": "market-metrics-test",
        "scoring_policy_fingerprint": model_version,
        "universe_name": universe_name,
        "universe_fingerprint": stable_fingerprint(tickers),
    }
    manifest = {
        "manifest_version": RUN_MANIFEST_VERSION,
        "application_version": "test",
        "database_schema_version": SCHEMA_VERSION,
        "calculation_contract": contract,
        "calculation_contract_fingerprint": stable_fingerprint(contract),
        "configuration_fingerprint": "test-config",
        "universe_members": [
            {"ticker": ticker, "company": ticker, "sector": "Test"} for ticker in tickers
        ],
        "environment": {},
    }
    manifest["manifest_fingerprint"] = stable_fingerprint(manifest)
    return manifest


def save_test_result(storage: Storage, run_id: str, ticker: str = "A") -> None:
    storage.save_results(
        run_id,
        [
            ScoredSecurity(
                ticker=ticker,
                company=ticker,
                sector="Test",
                latest_price=1.0,
                price_as_of="2026-01-01",
                metrics={},
                metric_scores={},
                component_scores={},
                component_coverage={},
                overall_score=50.0,
                overall_coverage=1.0,
                recommendation="Relative watchlist",
                eligible=True,
                eligibility_reasons=["test reason"],
                rank=1,
            )
        ],
    )


def test_result_eligibility_reasons_roundtrip(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    storage.create_run(
        AnalysisRun(
            run_id="eligibility",
            started_at=datetime.fromisoformat("2026-01-01T12:00:00+00:00"),
            completed_at=datetime.fromisoformat("2026-01-01T12:01:00+00:00"),
            as_of="2026-01-01",
            provider="test",
            universe_name="universe-a",
            model_version="model-a",
            config_snapshot={},
            status="completed",
            reproducibility_manifest=run_manifest("universe-a", "model-a"),
            reproducibility_status="recorded",
            reproducibility_reasons=[],
        )
    )
    save_test_result(storage, "eligibility")

    result = storage.get_results("eligibility")[0]

    assert result["eligibility_reasons"] == ["test reason"]


def test_storage_context_closes_database_connection(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")

    with storage.connect() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_previous_comparable_run_skips_other_models_and_universes(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    values = (
        ("matching", "2026-01-01", "universe-a", "model-a"),
        ("other-model", "2026-01-02", "universe-a", "model-b"),
        ("other-universe", "2026-01-03", "universe-b", "model-a"),
        ("current", "2026-01-04", "universe-a", "model-a"),
    )
    for run_id, as_of, universe_name, model_version in values:
        storage.create_run(
            AnalysisRun(
                run_id=run_id,
                started_at=datetime.fromisoformat(f"{as_of}T12:00:00+00:00"),
                completed_at=datetime.fromisoformat(f"{as_of}T12:01:00+00:00"),
                as_of=as_of,
                provider="test",
                universe_name=universe_name,
                model_version=model_version,
                config_snapshot={},
                status="completed",
                reproducibility_manifest=run_manifest(universe_name, model_version),
                reproducibility_status="recorded",
                reproducibility_reasons=[],
            )
        )
        save_test_result(storage, run_id)

    previous, reasons = storage.previous_comparable_run_assessment("current")

    assert previous is not None
    assert previous["run_id"] == "matching"
    assert reasons == ()


def test_previous_comparable_run_reports_only_the_nearest_candidate_limitations(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    runs = (
        ("older", "2026-01-01", run_manifest("universe-a", "model-b"), "A"),
        ("nearest", "2026-01-02", run_manifest("universe-a", "model-a"), "B"),
        ("current", "2026-01-03", run_manifest("universe-a", "model-a"), "A"),
    )
    for run_id, as_of, manifest, result_ticker in runs:
        storage.create_run(
            AnalysisRun(
                run_id=run_id,
                started_at=datetime.fromisoformat(f"{as_of}T12:00:00+00:00"),
                completed_at=datetime.fromisoformat(f"{as_of}T12:01:00+00:00"),
                as_of=as_of,
                provider="test",
                universe_name="universe-a",
                model_version="model-a",
                config_snapshot={},
                status="completed",
                reproducibility_manifest=manifest,
                reproducibility_status="recorded",
                reproducibility_reasons=[],
            )
        )
        save_test_result(storage, run_id, ticker=result_ticker)

    previous, reasons = storage.previous_comparable_run_assessment("current")

    assert previous is None
    assert reasons == ("Candidate run result membership does not match its manifest",)


def test_previous_comparable_run_handles_unknown_and_empty_history(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()

    assert storage.previous_comparable_run_assessment("unknown") == (
        None,
        ("Unknown analysis run: unknown",),
    )

    manifest = run_manifest("universe-a", "model-a")
    storage.create_run(
        AnalysisRun(
            run_id="current",
            started_at=datetime.fromisoformat("2026-01-01T12:00:00+00:00"),
            completed_at=datetime.fromisoformat("2026-01-01T12:01:00+00:00"),
            as_of="2026-01-01",
            provider="test",
            universe_name="universe-a",
            model_version="model-a",
            config_snapshot={},
            status="completed",
            reproducibility_manifest=manifest,
            reproducibility_status="recorded",
            reproducibility_reasons=[],
        )
    )
    save_test_result(storage, "current")

    assert storage.previous_comparable_run_assessment("current") == (
        None,
        ("No earlier completed run is stored",),
    )


def test_legacy_runs_are_limited_and_not_silently_comparable(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    for run_id, as_of in (("legacy", "2026-01-01"), ("current", "2026-01-02")):
        manifest = run_manifest("universe-a", "model-a") if run_id == "current" else None
        storage.create_run(
            AnalysisRun(
                run_id=run_id,
                started_at=datetime.fromisoformat(f"{as_of}T12:00:00+00:00"),
                completed_at=datetime.fromisoformat(f"{as_of}T12:01:00+00:00"),
                as_of=as_of,
                provider="test",
                universe_name="universe-a",
                model_version="model-a",
                config_snapshot={},
                status="completed",
                reproducibility_manifest=manifest,
                reproducibility_status="recorded" if manifest else "legacy_limited",
                reproducibility_reasons=[],
            )
        )
        save_test_result(storage, run_id)

    previous, reasons = storage.previous_comparable_run_assessment("current")

    assert previous is None
    assert any("Formal run reproducibility manifest" in reason for reason in reasons)
    with storage.connect() as connection:
        legacy = connection.execute(
            "SELECT reproducibility_status FROM analysis_runs WHERE run_id = 'legacy'"
        ).fetchone()
    assert legacy["reproducibility_status"] == "legacy_limited"


def test_run_comparison_rejects_result_membership_mismatch(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    manifest = run_manifest("universe-a", "model-a")
    for run_id, as_of in (("previous", "2026-01-01"), ("current", "2026-01-02")):
        storage.create_run(
            AnalysisRun(
                run_id=run_id,
                started_at=datetime.fromisoformat(f"{as_of}T12:00:00+00:00"),
                completed_at=datetime.fromisoformat(f"{as_of}T12:01:00+00:00"),
                as_of=as_of,
                provider="test",
                universe_name="universe-a",
                model_version="model-a",
                config_snapshot={},
                status="completed",
                reproducibility_manifest=manifest,
                reproducibility_status="recorded",
                reproducibility_reasons=[],
            )
        )
    save_test_result(storage, "previous")
    save_test_result(storage, "current", ticker="B")

    eligible, reasons = storage.run_comparison_eligibility("current", "previous")

    assert eligible is False
    assert "Current run result membership does not match its manifest" in reasons


def test_run_comparison_missing_run_precedes_manifest_loading(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    storage.create_run(
        AnalysisRun(
            run_id="existing",
            started_at=datetime.fromisoformat("2026-01-01T12:00:00+00:00"),
            completed_at=datetime.fromisoformat("2026-01-01T12:01:00+00:00"),
            as_of="2026-01-01",
            provider="test",
            universe_name="universe-a",
            model_version="model-a",
            config_snapshot={},
            status="completed",
            reproducibility_manifest=run_manifest("universe-a", "model-a"),
            reproducibility_status="recorded",
            reproducibility_reasons=[],
        )
    )
    with storage.connect() as connection:
        connection.execute(
            "UPDATE analysis_runs SET manifest_json = '{malformed' WHERE run_id = 'existing'"
        )

    assert storage.run_comparison_eligibility("unknown", "existing") == (
        False,
        ("Unknown analysis run: unknown",),
    )
    assert storage.run_comparison_eligibility("existing", "unknown") == (
        False,
        ("Unknown analysis run: unknown",),
    )


def test_normalized_cache_roundtrip(tmp_path):
    storage = Storage(tmp_path / "runtime" / "test.sqlite3")
    storage.initialize()
    fetched = datetime.now(UTC)
    bar = PriceBar("A", date(2026, 1, 2), 9, 11, 8, 10, 10, 100, "test", fetched)
    assert storage.upsert_price_bars([bar]) == 1
    assert storage.upsert_price_bars([bar]) == 1
    loaded = storage.get_price_bars("A", "test")
    assert len(loaded) == 1
    assert loaded[0].close == 10

    fundamental = FundamentalSnapshot(ticker="A", source="test", fetched_at=fetched, market_cap=123)
    storage.put_fundamental(fundamental, ttl_hours=2)
    assert storage.get_fundamental("A", "test", fresh_only=True).market_cap == 123


def test_cleanup_is_dry_run_by_default(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    old = PriceBar("A", date(2000, 1, 1), 9, 11, 8, 10, 10, 100, "test", datetime.now(UTC))
    storage.upsert_price_bars([old])
    preview = storage.cleanup_database(550, apply=False)
    assert preview["old_price_bars"] == 1
    assert len(storage.get_price_bars("A")) == 1
    storage.cleanup_database(550, apply=True)
    assert not storage.get_price_bars("A")


def test_provider_health_roundtrip(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    health = ProviderHealth(
        provider="sec-edgar",
        checked_at=datetime.now(UTC),
        status="healthy",
        endpoint="https://www.sec.gov/files/company_tickers_exchange.json",
        latency_ms=125.5,
        cache_hit=False,
        detail="identity_records=2; universe_matches=2/2",
    )
    storage.record_provider_health(health)
    loaded = storage.get_provider_health("sec-edgar")
    assert loaded is not None
    assert loaded.status == "healthy"
    assert loaded.latency_ms == 125.5
    assert loaded.cache_hit is False


def make_filing(accession_number: str, filing_date: date) -> SecFiling:
    return SecFiling(
        cik="0001045810",
        ticker="NVDA",
        company_name="NVIDIA CORP",
        accession_number=accession_number,
        form="10-Q",
        base_form="10-Q",
        is_amendment=False,
        filing_date=filing_date,
        report_date=filing_date,
        acceptance_datetime=f"{filing_date.isoformat()}T16:00:00Z",
        accepted_at=datetime.combine(filing_date, datetime.min.time(), tzinfo=UTC),
        availability_date=filing_date,
        availability_precision="timestamp",
        primary_document="filing.htm",
        filing_index_url="https://www.sec.gov/index.html",
        primary_document_url="https://www.sec.gov/filing.htm",
        source_url="https://data.sec.gov/submissions/CIK0001045810.json",
        fetched_at=datetime.now(UTC),
    )


def test_sec_filing_sync_roundtrip_and_deactivates_removed_rows(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    first = make_filing("0001045810-26-000001", date(2026, 1, 1))
    second = make_filing("0001045810-26-000002", date(2026, 4, 1))
    assert (
        storage.replace_sec_filings(
            ticker="NVDA",
            ciks=["0001045810"],
            since_date=date(2026, 1, 1),
            filings=[first, second],
        )
        == 2
    )
    assert len(storage.get_sec_filings("NVDA")) == 2
    storage.replace_sec_filings(
        ticker="NVDA",
        ciks=["0001045810"],
        since_date=date(2026, 1, 1),
        filings=[second],
    )
    assert [value.accession_number for value in storage.get_sec_filings("NVDA")] == [
        second.accession_number
    ]
    assert len(storage.get_sec_filings("NVDA", active_only=False)) == 2


def make_company_fact(accession_number: str, value: str) -> SecCompanyFact:
    filed = date(2026, 2, 20)
    return SecCompanyFact(
        cik="0001045810",
        ticker="NVDA",
        company_name="NVIDIA CORP",
        canonical_name="revenue",
        taxonomy="us-gaap",
        concept="Revenues",
        concept_priority=1,
        label="Revenue",
        description="Revenue from customers.",
        period_type="duration",
        unit="USD",
        value=Decimal(value),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        accession_number=accession_number,
        fiscal_year=2025,
        fiscal_period="FY",
        form="10-K",
        filed_date=filed,
        frame="CY2025",
        accepted_at=datetime(2026, 2, 20, 21, 0, tzinfo=UTC),
        availability_date=filed,
        availability_precision="timestamp",
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json",
        fetched_at=datetime.now(UTC),
    )


def test_sec_company_fact_roundtrip_updates_values_and_deactivates_removed_rows(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    first = make_company_fact("0001045810-26-000001", "100.25")
    second = make_company_fact("0001045810-26-000002", "110")
    assert (
        storage.replace_sec_company_facts(
            ticker="NVDA",
            ciks=["0001045810"],
            since_date=date(2026, 1, 1),
            facts=[first, second],
        )
        == 2
    )
    loaded = storage.get_sec_company_facts("NVDA", canonical_name="revenue")
    assert {fact.value for fact in loaded} == {Decimal("100.25"), Decimal(110)}

    corrected = make_company_fact(first.accession_number, "101.5")
    storage.replace_sec_company_facts(
        ticker="NVDA",
        ciks=["0001045810"],
        since_date=date(2026, 1, 1),
        facts=[corrected],
    )
    active = storage.get_sec_company_facts("NVDA")
    assert len(active) == 1
    assert active[0].value == Decimal("101.5")
    assert len(storage.get_sec_company_facts("NVDA", active_only=False)) == 2
    observations = storage.get_sec_company_fact_observations(ticker="NVDA")
    assert len(observations) == 3
    original_key = storage._sec_fact_key(first)
    revisions = [
        observation for observation in observations if observation["fact_key"] == original_key
    ]
    assert {revision["payload"]["value"] for revision in revisions} == {"100.25", "101.5"}
    assert len({revision["payload_fingerprint"] for revision in revisions}) == 2
    assert {revision["observation_status"] for revision in revisions} == {"observed"}


def test_sec_company_fact_identical_refresh_updates_observation_seen_time(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    fact = make_company_fact("0001045810-26-000001", "100.25")
    for _ in range(2):
        storage.replace_sec_company_facts(
            ticker="NVDA",
            ciks=["0001045810"],
            since_date=date(2026, 1, 1),
            facts=[fact],
        )

    observations = storage.get_sec_company_fact_observations(ticker="NVDA")
    assert len(observations) == 1
    assert observations[0]["first_seen_at"] <= observations[0]["last_seen_at"]


def test_sec_company_fact_vintages_use_only_observations_known_by_cutoff(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    storage.create_run(
        AnalysisRun(
            run_id="ranking-isolation",
            started_at=datetime(2026, 2, 21, 10, 0, tzinfo=UTC),
            completed_at=datetime(2026, 2, 21, 10, 1, tzinfo=UTC),
            as_of="2026-02-20",
            provider="test",
            universe_name="universe-a",
            model_version="model-a",
            config_snapshot={},
            status="completed",
            reproducibility_manifest=run_manifest("universe-a", "model-a"),
            reproducibility_status="recorded",
            reproducibility_reasons=[],
        )
    )
    save_test_result(storage, "ranking-isolation")
    ranking_before = storage.get_results("ranking-isolation")
    first_observed_at = datetime(2026, 2, 21, 12, 0, tzinfo=UTC)
    corrected_at = datetime(2026, 2, 22, 12, 0, tzinfo=UTC)
    original = replace(
        make_company_fact("0001045810-26-000001", "100.25"),
        fetched_at=first_observed_at,
    )
    corrected = replace(original, value=Decimal("101.5"), fetched_at=corrected_at)
    for value in (original, corrected):
        storage.replace_sec_company_facts(
            ticker="NVDA",
            ciks=["0001045810"],
            since_date=date(2026, 1, 1),
            facts=[value],
        )

    assert (
        storage.get_sec_company_facts_as_of("NVDA", first_observed_at - timedelta(microseconds=1))
        == []
    )
    assert [
        fact.value for fact in storage.get_sec_company_facts_as_of("NVDA", first_observed_at)
    ] == [Decimal("100.25")]
    assert [
        fact.value
        for fact in storage.get_sec_company_facts_as_of(
            "NVDA", corrected_at - timedelta(microseconds=1)
        )
    ] == [Decimal("100.25")]
    assert [fact.value for fact in storage.get_sec_company_facts_as_of("NVDA", corrected_at)] == [
        Decimal("101.5")
    ]
    assert storage.get_results("ranking-isolation") == ranking_before


def test_sec_company_fact_vintages_preserve_amendments_for_effective_selection(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    observed_at = datetime(2026, 2, 22, 12, 0, tzinfo=UTC)
    original = replace(
        make_company_fact("0001045810-26-000001", "100.25"),
        fetched_at=observed_at,
    )
    amendment = replace(
        make_company_fact("0001045810-26-000002", "110"),
        accepted_at=datetime(2026, 2, 21, 21, 0, tzinfo=UTC),
        fetched_at=observed_at,
    )
    storage.replace_sec_company_facts(
        ticker="NVDA",
        ciks=["0001045810"],
        since_date=date(2026, 1, 1),
        facts=[original, amendment],
    )

    vintages = tuple(storage.get_sec_company_facts_as_of("NVDA", observed_at))
    effective = SecCompanyFacts.effective_facts(vintages, available_at=observed_at)

    assert len(vintages) == 2
    assert [fact.value for fact in effective] == [Decimal(110)]


def test_sec_company_fact_vintage_cutoff_must_be_timezone_aware(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()

    with pytest.raises(ValueError, match="cutoff must include a timezone"):
        storage.get_sec_company_facts_as_of(
            "NVDA", datetime(2026, 2, 21, 12, 0, tzinfo=UTC).replace(tzinfo=None)
        )


def test_initialize_seeds_legacy_sec_fact_observation(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    fact = make_company_fact("0001045810-26-000001", "100.25")
    storage.replace_sec_company_facts(
        ticker="NVDA",
        ciks=["0001045810"],
        since_date=date(2026, 1, 1),
        facts=[fact],
    )
    with storage.connect() as connection:
        connection.execute("DROP TABLE sec_company_fact_observations")

    storage.initialize()

    observations = storage.get_sec_company_fact_observations(ticker="NVDA")
    assert len(observations) == 1
    assert observations[0]["payload"]["value"] == "100.25"
    assert observations[0]["observation_status"] == "legacy_seed"
    observed_at = datetime.fromisoformat(observations[0]["observed_at"])
    assert (
        storage.get_sec_company_facts_as_of("NVDA", observed_at - timedelta(microseconds=1)) == []
    )
    assert [fact.value for fact in storage.get_sec_company_facts_as_of("NVDA", observed_at)] == [
        Decimal("100.25")
    ]


def test_sec_companyfacts_refresh_state_roundtrip(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    refreshed_at = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    value = SecCompanyFactsRefreshState(
        ticker="NVDA",
        identity_fingerprint="identity-v1",
        filing_fingerprint="filings-v1",
        config_fingerprint="config-v1",
        last_successful_refresh_at=refreshed_at,
        latest_filing_at=refreshed_at - timedelta(days=1),
        unmatched_accessions=2,
        last_refresh_reason="new or changed SEC filing",
    )
    storage.save_sec_companyfacts_refresh_state(value)
    assert storage.get_sec_companyfacts_refresh_state("NVDA") == value
    assert storage.get_sec_companyfacts_refresh_state("AAPL") is None
