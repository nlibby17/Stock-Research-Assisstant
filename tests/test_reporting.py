from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from stockrank.config import load_settings
from stockrank.models import AnalysisRun, ScoredSecurity, SecFiling
from stockrank.reporting import _stored_run_as_of, render_report
from stockrank.storage import Storage


def test_historical_report_date_comes_from_requested_run(tmp_path):
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    for run_id, as_of in (("older-run", "2026-01-02"), ("newer-run", "2026-08-28")):
        storage.create_run(
            AnalysisRun(
                run_id=run_id,
                started_at=datetime.fromisoformat(f"{as_of}T12:00:00+00:00"),
                completed_at=datetime.fromisoformat(f"{as_of}T12:01:00+00:00"),
                as_of=as_of,
                provider="test",
                universe_name="test",
                model_version="test",
                config_snapshot={},
                status="completed",
            )
        )
    assert _stored_run_as_of(storage, "older-run") == "2026-01-02"
    with pytest.raises(ValueError, match="Unknown run_id"):
        _stored_run_as_of(storage, "missing")


def _report_result(*, eligible: bool) -> ScoredSecurity:
    return ScoredSecurity(
        ticker="AAA",
        company="AAA Company",
        sector="Industrials",
        latest_price=10.0,
        price_as_of="2026-08-31",
        metrics={"average_dollar_volume_20d": 2_000_000.0},
        metric_scores={"revenue_growth": 60.0},
        component_scores={component: 60.0 for component in (
            "growth", "valuation", "quality", "momentum", "risk"
        )},
        component_coverage={component: 1.0 for component in (
            "growth", "valuation", "quality", "momentum", "risk"
        )},
        overall_score=60.0 if eligible else 50.0,
        overall_coverage=1.0,
        recommendation="Relative watchlist",
        eligible=eligible,
        rank=1,
    )


def _save_report_run(
    storage: Storage,
    config: dict,
    *,
    completed_at: datetime | None,
    eligible: bool,
) -> None:
    storage.create_run(
        AnalysisRun(
            run_id="report-run",
            started_at=datetime(2026, 8, 31, 12, tzinfo=UTC),
            completed_at=completed_at,
            as_of="2026-08-31",
            provider="test",
            universe_name="test",
            model_version="test",
            config_snapshot=config,
            status="completed",
        )
    )
    storage.save_results("report-run", [_report_result(eligible=eligible)])


def test_report_withholds_filings_when_run_has_no_aware_completion_cutoff(tmp_path):
    settings = load_settings(Path.cwd())
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    _save_report_run(storage, deepcopy(settings.raw), completed_at=None, eligible=True)
    filing = SecFiling(
        cik="0000000001",
        ticker="AAA",
        company_name="AAA Company",
        accession_number="filing-after-unknown-cutoff",
        form="10-Q",
        base_form="10-Q",
        is_amendment=False,
        filing_date=date(2026, 8, 31),
        report_date=date(2026, 6, 30),
        acceptance_datetime="2026-08-31T13:00:00+00:00",
        accepted_at=datetime(2026, 8, 31, 13, tzinfo=UTC),
        availability_date=date(2026, 8, 31),
        availability_precision="timestamp",
        primary_document="aaa.htm",
        filing_index_url="https://example.test/filing",
        primary_document_url=None,
        source_url="https://example.test/submissions",
        fetched_at=datetime(2026, 8, 31, 14, tzinfo=UTC),
    )
    storage.replace_sec_filings(
        ticker="AAA",
        ciks=(filing.cik,),
        since_date=date(2026, 1, 1),
        filings=(filing,),
    )

    report = render_report(settings, storage, "report-run")

    assert "SEC filing metadata is withheld" in report
    assert filing.filing_index_url not in report


def test_report_empty_candidate_message_uses_stored_complete_policy(tmp_path):
    settings = load_settings(Path.cwd())
    storage = Storage(tmp_path / "test.sqlite3")
    storage.initialize()
    _save_report_run(
        storage,
        deepcopy(settings.raw),
        completed_at=datetime(2026, 8, 31, 12, 1, tzinfo=UTC),
        eligible=False,
    )

    report = render_report(settings, storage, "report-run")

    assert "all stored candidate eligibility rules" in report
    assert "score ≥ 55" in report
    assert "coverage ≥ 60%" in report
    assert "price ≥ $1.00" in report
    assert "20-day average dollar volume ≥ $1,000,000" in report
