from __future__ import annotations

import copy
import shutil
from argparse import Namespace
from pathlib import Path

import pytest

from stockrank import cli
from stockrank.config import Settings, load_settings, validate_settings
from stockrank.customization import (
    enrich_universe,
    model_identifier,
    parse_component_weights,
    profile_weights,
    universe_identifier,
)
from stockrank.models import FundamentalSnapshot, Security


def _project_config(tmp_path: Path) -> None:
    source = Path.cwd() / "config"
    target = tmp_path / "config"
    target.mkdir()
    shutil.copy(source / "preferences.toml", target / "preferences.toml")
    shutil.copy(source / "universe.csv", target / "universe.csv")


def test_profiles_are_deterministic_normalized_and_meaningful():
    balanced = profile_weights("balanced", "moderate", "medium")
    aggressive_growth = profile_weights("growth", "aggressive", "long")
    conservative = profile_weights("lower_volatility", "conservative", "long")
    assert sum(balanced.values()) == pytest.approx(1)
    assert sum(aggressive_growth.values()) == pytest.approx(1)
    assert aggressive_growth["growth"] > balanced["growth"]
    assert conservative["risk"] > balanced["risk"]
    assert (
        parse_component_weights("growth=.25,valuation=.20,quality=.25,momentum=.20,risk=.10")
        == balanced
    )
    with pytest.raises(ValueError, match="total 1.0"):
        parse_component_weights("growth=.50,valuation=.20,quality=.25,momentum=.20,risk=.10")


def test_identifiers_change_with_scoring_and_universe():
    loaded = load_settings(Path.cwd())
    first = model_identifier("balanced", loaded.raw["scoring"], loaded.component_weights)
    changed_weights = dict(loaded.component_weights, growth=0.30, valuation=0.15)
    second = model_identifier("balanced", loaded.raw["scoring"], changed_weights)
    assert first != second
    securities = [Security("A", "Alpha", "Industrials")]
    assert universe_identifier(securities) != universe_identifier(
        securities + [Security("B", "Beta", "Industrials")]
    )


def test_validation_rejects_bad_sector_and_weights():
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["scoring"]["overall"]["growth"] = -1
    settings = Settings(
        root=loaded.root,
        raw=raw,
        universe=(Security("TEST", "Test", "Not A Sector"),),
    )
    errors, warnings = validate_settings(settings)
    assert any("nonnegative" in error for error in errors)
    assert any("unsupported sector" in error for error in errors)
    assert any("below 10" in warning for warning in warnings)

    version_mismatch_raw = copy.deepcopy(loaded.raw)
    version_mismatch_raw["scoring"]["overall"].update({"growth": 0.30, "valuation": 0.15})
    mismatch = Settings(
        root=loaded.root,
        raw=version_mismatch_raw,
        universe=loaded.universe,
    )
    mismatch_errors, _ = validate_settings(mismatch)
    assert any("registered weights" in error for error in mismatch_errors)


def test_validation_rejects_invalid_freshness_limits():
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["provider"]["maximum_price_age_hours"] = 0
    raw["provider"]["maximum_stale_fundamental_hours"] = -1
    raw["provider"]["daily_bar_completion_buffer_minutes"] = 181
    settings = Settings(root=loaded.root, raw=raw, universe=loaded.universe)

    errors, _ = validate_settings(settings)

    assert any("maximum_price_age_hours" in error for error in errors)
    assert any("maximum_stale_fundamental_hours" in error for error in errors)
    assert any("daily_bar_completion_buffer_minutes" in error for error in errors)


def test_metadata_enrichment_maps_yahoo_sector():
    class Provider:
        def fetch_fundamental(self, security):
            return (
                FundamentalSnapshot(
                    ticker=security.ticker,
                    source="test",
                    fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                    company="Example Corp",
                    sector="Technology",
                ),
                [],
            )

    values, warnings = enrich_universe([Security("TEST", "", "")], provider=Provider())
    assert values == [Security("TEST", "Example Corp", "Information Technology")]
    assert not warnings


def test_noninteractive_configuration_writes_local_files_and_loads_them(tmp_path, monkeypatch):
    _project_config(tmp_path)
    custom = tmp_path / "custom.csv"
    custom.write_text(
        "ticker,company,sector\nMSFT,Microsoft,Information Technology\n"
        "JPM,JPMorgan Chase,Financials\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    args = Namespace(
        reset=False,
        yes=True,
        profile="quality",
        horizon="long",
        risk="conservative",
        weights=None,
        candidate_limit=5,
        minimum_score=60,
        minimum_coverage=0.7,
        tickers=None,
        universe_file=str(custom),
    )
    assert cli.command_configure(args) == 0
    settings = load_settings(tmp_path)
    assert settings.uses_local_preferences
    assert settings.profile_name == "quality"
    assert settings.model_version.startswith("custom-quality-")
    assert [security.ticker for security in settings.universe] == ["MSFT", "JPM"]
    assert (tmp_path / "config" / "preferences.local.toml").is_file()
    assert (tmp_path / "config" / "universe.local.csv").is_file()

    updated = Namespace(**vars(args))
    updated.profile = "growth"
    updated.universe_file = None
    assert cli.command_configure(updated) == 0
    assert (tmp_path / "config" / "preferences.local.toml.bak").is_file()


def test_personal_files_are_ignored_by_git():
    ignore = (Path.cwd() / ".gitignore").read_text(encoding="utf-8")
    assert "config/preferences.local.toml*" in ignore
    assert "config/universe.local.csv*" in ignore


def test_example_local_configuration_is_usable(tmp_path):
    _project_config(tmp_path)
    source = Path.cwd() / "config"
    shutil.copy(
        source / "preferences.local.example.toml",
        tmp_path / "config" / "preferences.local.toml",
    )
    shutil.copy(
        source / "universe.local.example.csv",
        tmp_path / "config" / "universe.local.csv",
    )

    settings = load_settings(tmp_path)
    errors, warnings = validate_settings(settings)

    assert not errors
    assert [security.ticker for security in settings.universe] == ["MSFT", "JPM"]
    assert warnings == [
        (
            "Custom profile predates calculation-version tracking; rerun `stockrank "
            "configure` before the next report to create a fully versioned model identifier"
        ),
        "Universes below 10 stocks produce unstable percentile rankings",
    ]
