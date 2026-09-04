from __future__ import annotations

from argparse import Namespace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from stockrank import cli


def test_shadow_command_records_and_enforces_the_actual_formula_contract(monkeypatch, capsys):
    manifest = {"semantic_version": "sec-financials-v1.1.0", "fingerprint": "supported"}
    settings = SimpleNamespace(
        database_path="unused.sqlite3",
        provider_name="yfinance",
        model_version="ranking-v1",
        universe=(
            SimpleNamespace(ticker="AAA", sector="Technology"),
            SimpleNamespace(ticker="BBB", sector="Industrials"),
        ),
        raw={"app": {"timezone": "UTC"}, "universe": {"name": "test-universe"}},
    )
    comparison_config = SimpleNamespace(
        version="provider-shadow-test",
        metrics=(SimpleNamespace(name="revenue"),),
        required_full_universe_dates=3,
    )
    completed_at = datetime.now(UTC) - timedelta(minutes=1)

    class FakeStorage:
        saved_run = None
        health = None

        def initialize(self):
            pass

        def latest_sec_financial_snapshot(self, ticker, *, available_at):
            return SimpleNamespace(
                formula_version="sec-financials-v1.1.0",
                formula_manifest=manifest,
            )

        def get_fundamental(self, ticker, provider, *, fresh_only):
            return object()

        def latest_run(self):
            return {
                "run_id": "analysis-1",
                "status": "completed",
                "provider": "yfinance",
                "universe_name": "test-universe",
                "completed_at": completed_at.isoformat(),
                "as_of": "2026-09-03",
                "warnings_json": "[]",
            }

        def get_results(self, run_id):
            return [
                {"ticker": "AAA", "price_as_of": "2026-09-03"},
                {"ticker": "BBB", "price_as_of": "2026-09-03"},
            ]

        def save_provider_comparison_run(self, run, comparisons):
            self.saved_run = run
            return len(comparisons)

        def provider_comparison_full_universe_dates(self, *args, **kwargs):
            return 1

        def record_provider_health(self, health):
            self.health = health

    storage = FakeStorage()

    def comparison(**values):
        return (
            SimpleNamespace(
                comparison_run_id=values["comparison_run_id"],
                ticker=values["ticker"],
                metric_name="revenue",
                classification="comparable",
                fallback_candidate=None,
                sec_value=100,
                yahoo_value=101,
                relative_difference=None,
            ),
        )

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "Storage", lambda path: storage)
    monkeypatch.setattr(cli, "load_provider_comparison_config", lambda current: comparison_config)
    monkeypatch.setattr(cli, "load_sec_concept_specs", lambda current: ())
    monkeypatch.setattr(cli, "formula_manifest", lambda *, concept_specs: manifest)
    monkeypatch.setattr(cli, "compare_provider_metrics", comparison)

    result = cli.command_provider_shadow_run(Namespace(ticker=None))

    assert result == 0
    assert storage.saved_run.evidence_qualified is True
    assert storage.saved_run.analysis_run_id == "analysis-1"
    assert storage.saved_run.evidence_date == date(2026, 9, 3)
    assert storage.saved_run.formula_contracts == (
        {
            "formula_version": "sec-financials-v1.1.0",
            "formula_manifest": manifest,
        },
    )
    assert storage.health.status == "healthy"
    assert "supported SEC formula contract" in storage.saved_run.evidence_reason
    output = capsys.readouterr().out
    assert "sec-financials-v1.1.0@supported" in output
