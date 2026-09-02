from __future__ import annotations

import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from stockrank.config import load_settings
from stockrank.models import AnalysisRun, ScoredSecurity
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

    app = _run_dashboard(root, monkeypatch)

    assert not app.exception
    assert any("filing metadata is withheld" in item.value for item in app.caption)


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
