import copy
from pathlib import Path

from stockrank.config import Settings, load_settings
from stockrank.pipeline import run_analysis
from stockrank.storage import Storage


def test_versioned_universe_has_50_unique_stocks_and_all_sectors():
    settings = load_settings(Path.cwd())
    assert settings.raw["universe"]["name"] == "us_diversified_50_v1"
    assert len(settings.universe) == 50
    assert len({security.ticker for security in settings.universe}) == 50
    assert len({security.sector for security in settings.universe}) == 11
    assert settings.raw["universe"]["maintenance_mode"] == "manual_curated"


def test_demo_pipeline_end_to_end(tmp_path):
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["provider"]["price_history_days"] = 420
    raw["app"]["runtime_dir"] = "runtime"
    settings = Settings(root=tmp_path, raw=raw, universe=loaded.universe[:8])
    run_id, report_path, warnings = run_analysis(settings, demo=True)
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert run_id in text
    assert "demo-synthetic" in text
    assert "SYNTHETIC" in " ".join(warnings).upper()
    storage = Storage(settings.database_path)
    run = storage.latest_run()
    assert run["status"] == "completed"
    assert len(storage.get_results(run_id)) == 8
    assert (settings.runtime_dir / "reports" / "research_template.json").exists()
