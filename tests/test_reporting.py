from __future__ import annotations

from datetime import datetime

import pytest

from stockrank.models import AnalysisRun
from stockrank.reporting import _stored_run_as_of
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
