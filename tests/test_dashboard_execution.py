from __future__ import annotations

import shutil
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from stockrank.config import load_settings
from stockrank.models import (
    AnalysisRun,
    ProviderComparisonRun,
    ProviderHealth,
    ScoredSecurity,
    SecFinancialSnapshot,
)
from stockrank.provider_comparison import load_provider_comparison_config
from stockrank.storage import Storage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = PROJECT_ROOT / "src" / "stockrank" / "dashboard.py"


def _isolated_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT / "config", root / "config")
    for private_name in ("preferences.local.toml", "universe.local.csv"):
        (root / "config" / private_name).unlink(missing_ok=True)
    return root


def _save_run(
    root: Path,
    *,
    completed_at: datetime | None,
    eligible: bool,
    full_policy: bool = True,
) -> None:
    settings = load_settings(root)
    storage = Storage(settings.database_path)
    storage.initialize()
    config = deepcopy(settings.raw) if full_policy else {}
    storage.create_run(
        AnalysisRun(
            run_id="dashboard-run",
            started_at=datetime(2026, 8, 31, 12, tzinfo=UTC),
            completed_at=completed_at,
            as_of="2026-08-31",
            provider="test-provider",
            universe_name="test-universe",
            model_version="test-model",
            config_snapshot=config,
            status="completed",
        )
    )
    storage.save_results(
        "dashboard-run",
        [
            ScoredSecurity(
                ticker="AAPL",
                company="Apple Inc.",
                sector="Information Technology",
                latest_price=200.0,
                price_as_of="2026-08-31",
                metrics={"average_dollar_volume_20d": 2_000_000.0},
                metric_scores={"revenue_growth": 70.0},
                component_scores={
                    "growth": 70.0,
                    "valuation": 65.0,
                    "quality": 75.0,
                    "momentum": 60.0,
                    "risk": 55.0,
                },
                component_coverage={
                    "growth": 1.0,
                    "valuation": 1.0,
                    "quality": 1.0,
                    "momentum": 1.0,
                    "risk": 1.0,
                },
                overall_score=70.0 if eligible else 50.0,
                overall_coverage=1.0,
                recommendation="High relative score",
                eligible=eligible,
                rank=1,
            )
        ],
    )


def _run_dashboard(root: Path, monkeypatch) -> AppTest:
    monkeypatch.chdir(root)
    return AppTest.from_file(DASHBOARD_PATH, default_timeout=10).run()


def _save_financial_snapshot(
    storage: Storage,
    *,
    snapshot_id: str,
    ticker: str,
    as_of: datetime,
    built_at: datetime,
    formula_version: str,
) -> None:
    storage.save_sec_financial_snapshot(
        SecFinancialSnapshot(
            snapshot_id=snapshot_id,
            ticker=ticker,
            company_name=f"{ticker} Company",
            sector="Test sector",
            as_of=as_of,
            built_at=built_at,
            formula_version=formula_version,
            status="complete",
            warnings=(),
            metrics=(),
        )
    )


def _save_comparison_run(storage: Storage, run: ProviderComparisonRun) -> None:
    storage.save_provider_comparison_run(run, ())


def test_dashboard_executes_with_no_saved_run(tmp_path, monkeypatch):
    root = _isolated_project(tmp_path)

    app = _run_dashboard(root, monkeypatch)

    assert not app.exception
    assert any("No run exists yet" in item.value for item in app.info)


def test_dashboard_executes_current_completed_run(tmp_path, monkeypatch):
    root = _isolated_project(tmp_path)
    _save_run(
        root,
        completed_at=datetime(2026, 8, 31, 12, 1, tzinfo=UTC),
        eligible=True,
    )

    app = _run_dashboard(root, monkeypatch)

    assert not app.exception
    assert any(item.value == "Top Candidates Within This Universe" for item in app.header)
    assert not any("filing metadata is withheld" in item.value for item in app.caption)


def test_dashboard_executes_legacy_run_and_withholds_unbounded_filings(
    tmp_path, monkeypatch
):
    root = _isolated_project(tmp_path)
    _save_run(root, completed_at=None, eligible=True, full_policy=False)
    settings = load_settings(root)
    storage = Storage(settings.database_path)
    _save_financial_snapshot(
        storage,
        snapshot_id="current-only-snapshot",
        ticker="AAPL",
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        built_at=datetime(2026, 9, 1, tzinfo=UTC),
        formula_version="current-only",
    )

    app = _run_dashboard(root, monkeypatch)

    assert not app.exception
    assert any("filing metadata is withheld" in item.value for item in app.caption)
    assert any("SEC financial snapshots are withheld" in item.value for item in app.info)


def test_dashboard_no_candidate_message_uses_all_stored_rules(tmp_path, monkeypatch):
    root = _isolated_project(tmp_path)
    _save_run(
        root,
        completed_at=datetime(2026, 8, 31, 12, 1, tzinfo=UTC),
        eligible=False,
    )

    app = _run_dashboard(root, monkeypatch)

    assert not app.exception
    message = next(
        item.value for item in app.info if "stored candidate eligibility rules" in item.value
    )
    assert "score ≥ 55" in message
    assert "coverage ≥ 60%" in message
    assert "price ≥ $1.00" in message
    assert "20-day average dollar volume ≥ $1,000,000" in message


def test_dashboard_separates_report_evidence_from_current_diagnostics(
    tmp_path, monkeypatch
):
    root = _isolated_project(tmp_path)
    report_cutoff = datetime(2026, 8, 31, 12, 1, tzinfo=UTC)
    _save_run(root, completed_at=report_cutoff, eligible=True)
    settings = load_settings(root)
    storage = Storage(settings.database_path)
    active_universe_name = str(settings.raw["universe"]["name"])
    active_policy = load_provider_comparison_config(settings)

    _save_financial_snapshot(
        storage,
        snapshot_id="report-snapshot",
        ticker="AAPL",
        as_of=report_cutoff - timedelta(minutes=5),
        built_at=report_cutoff - timedelta(minutes=4),
        formula_version="report-formula",
    )
    _save_financial_snapshot(
        storage,
        snapshot_id="future-built-snapshot",
        ticker="AAPL",
        as_of=report_cutoff - timedelta(minutes=3),
        built_at=report_cutoff + timedelta(days=1),
        formula_version="future-formula",
    )
    _save_financial_snapshot(
        storage,
        snapshot_id="active-only-snapshot",
        ticker="MSFT",
        as_of=report_cutoff - timedelta(minutes=5),
        built_at=report_cutoff - timedelta(minutes=4),
        formula_version="active-only-formula",
    )
    linked_shadow = ProviderComparisonRun(
        comparison_run_id="linked-shadow",
        started_at=report_cutoff + timedelta(seconds=1),
        completed_at=report_cutoff + timedelta(seconds=2),
        as_of=report_cutoff + timedelta(seconds=1),
        config_version="stored-shadow-policy",
        universe_name="test-universe",
        scope_count=1,
        universe_size=1,
        full_universe=True,
        status="complete",
        warnings=(),
        analysis_run_id="dashboard-run",
        evidence_qualified=True,
        evidence_reason="Qualified stored evidence",
        formula_contracts=(
            {
                "formula_version": "report-formula",
                "formula_manifest": {"fingerprint": "report-formula-fingerprint"},
            },
        ),
    )
    _save_comparison_run(storage, linked_shadow)
    current_shadow = ProviderComparisonRun(
        comparison_run_id="current-shadow",
        started_at=report_cutoff + timedelta(days=1),
        completed_at=report_cutoff + timedelta(days=1, seconds=1),
        as_of=report_cutoff + timedelta(days=1),
        config_version=active_policy.version,
        universe_name=active_universe_name,
        scope_count=len(settings.universe),
        universe_size=len(settings.universe),
        full_universe=True,
        status="complete",
        warnings=(),
        analysis_run_id="different-analysis-run",
        evidence_qualified=True,
        evidence_reason="Qualified current evidence",
        formula_contracts=(
            {
                "formula_version": "current-formula",
                "formula_manifest": {"fingerprint": "current-formula-fingerprint"},
            },
        ),
    )
    _save_comparison_run(storage, current_shadow)
    storage.record_provider_health(
        ProviderHealth(
            provider="provider-shadow",
            checked_at=report_cutoff + timedelta(days=1, seconds=2),
            status="healthy",
            endpoint="local://provider-shadow",
            latency_ms=12,
            cache_hit=False,
            detail="comparison complete",
        )
    )

    app = _run_dashboard(root, monkeypatch)

    assert not app.exception
    financial_table = next(
        item.value
        for item in app.dataframe
        if {"Ticker", "Snapshot as of", "Formula"}.issubset(item.value.columns)
    )
    assert financial_table["Ticker"].tolist() == ["AAPL"]
    assert financial_table["Formula"].tolist() == ["report-formula"]
    captions = [item.value for item in app.caption]
    assert any(
        "Report-bound SEC evidence" in value
        and "stored universe test-universe" in value
        and "cutoff 2026-08-31T12:01:00+00:00" in value
        for value in captions
    )
    assert any(
        "Report-bound provider comparison · linked-shadow" in value
        and "analysis run dashboard-run" in value
        and "stored-shadow-policy" in value
        for value in captions
    )
    assert any(
        "Stored SEC formula contracts" in value and "report-formula@report-formu" in value
        for value in captions
    )
    assert any(
        "Installation-current diagnostics" in value
        and active_universe_name in value
        and active_policy.version in value
        and "report-bound policy stored-shadow-policy" in value
        and "policy differs from the report-bound comparison" in value
        and "differs from displayed report" in value
        for value in captions
    )
    assert any(
        "Installation-current Step 2.4B progress" in value
        and "current-shadow" in value
        and "not linked to the displayed report" in value
        for value in captions
    )


def test_dashboard_does_not_replace_missing_report_shadow_evidence(
    tmp_path, monkeypatch
):
    root = _isolated_project(tmp_path)
    report_cutoff = datetime(2026, 8, 31, 12, 1, tzinfo=UTC)
    _save_run(root, completed_at=report_cutoff, eligible=True)
    settings = load_settings(root)
    storage = Storage(settings.database_path)
    active_policy = load_provider_comparison_config(settings)
    _save_comparison_run(
        storage,
        ProviderComparisonRun(
            comparison_run_id="unrelated-shadow",
            started_at=report_cutoff + timedelta(days=1),
            completed_at=report_cutoff + timedelta(days=1, seconds=1),
            as_of=report_cutoff + timedelta(days=1),
            config_version=active_policy.version,
            universe_name=str(settings.raw["universe"]["name"]),
            scope_count=len(settings.universe),
            universe_size=len(settings.universe),
            full_universe=True,
            status="complete",
            warnings=(),
            analysis_run_id="different-analysis-run",
        ),
    )

    app = _run_dashboard(root, monkeypatch)

    assert not app.exception
    assert any(
        "No provider comparison is linked to displayed analysis run dashboard-run"
        in item.value
        for item in app.info
    )
