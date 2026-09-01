from __future__ import annotations

import copy
import shutil
from argparse import Namespace
from pathlib import Path

import pytest

from stockrank import cli, customization
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
    shutil.copy(source / "sec_companyfacts.toml", target / "sec_companyfacts.toml")
    shutil.copy(source / "sec_entity_overrides.toml", target / "sec_entity_overrides.toml")


def _personalization_kwargs(profile: str = "quality") -> dict:
    root = Path.cwd()
    loaded = load_settings(root, root / "config" / "preferences.toml")
    weights = profile_weights(profile, "moderate", "medium")
    securities = [
        Security("MSFT", "Microsoft", "Information Technology"),
        Security("JPM", "JPMorgan Chase", "Financials"),
    ]
    return {
        "securities": securities,
        "profile": profile,
        "horizon": "medium",
        "risk": "moderate",
        "weights": weights,
        "model_version": model_identifier(profile, loaded.raw["scoring"], weights),
        "universe_name": universe_identifier(securities),
        "universe_path": "config/universe.local.csv",
        "candidate_limit": 5,
        "minimum_score": 60,
        "minimum_coverage": 0.7,
    }


def _seed_personalization(tmp_path: Path) -> tuple[bytes, bytes]:
    customization.save_local_customization(tmp_path, **_personalization_kwargs())
    preferences = tmp_path / "config" / "preferences.local.toml"
    universe = tmp_path / "config" / "universe.local.csv"
    return preferences.read_bytes(), universe.read_bytes()


def _assert_personalization_bytes(tmp_path: Path, expected: tuple[bytes, bytes]) -> None:
    preferences = tmp_path / "config" / "preferences.local.toml"
    universe = tmp_path / "config" / "universe.local.csv"
    assert (preferences.read_bytes(), universe.read_bytes()) == expected


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
    assert any("registered policy" in error for error in mismatch_errors)


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


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("price_history_days", 0),
        ("report_days", -1),
        ("temporary_file_days", 0),
        ("price_history_days", 36501),
        ("report_days", 36501),
        ("temporary_file_days", 36501),
    ],
)
def test_validation_rejects_unbounded_retention_days(name, value):
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["retention"][name] = value
    settings = Settings(root=loaded.root, raw=raw, universe=loaded.universe)

    errors, _ = validate_settings(settings)

    assert any(f"retention.{name}" in error for error in errors)


def test_validation_rejects_nonpositive_liquidity_floors():
    loaded = load_settings(Path.cwd())
    raw = copy.deepcopy(loaded.raw)
    raw["scoring"]["eligibility"]["minimum_latest_price"] = 0
    raw["scoring"]["eligibility"]["minimum_average_dollar_volume_20d"] = -1
    settings = Settings(root=loaded.root, raw=raw, universe=loaded.universe)

    errors, _ = validate_settings(settings)

    assert any("minimum_latest_price" in error for error in errors)
    assert any("minimum_average_dollar_volume_20d" in error for error in errors)


def test_v1_1_custom_profile_is_accepted_with_upgrade_warning():
    loaded = load_settings(Path.cwd())
    legacy_scoring = copy.deepcopy(loaded.raw["scoring"])
    legacy_scoring.pop("eligibility")
    legacy_scoring.pop("validity")
    legacy_scoring["calculation_version"] = "market-metrics-v1.1.0"
    legacy_identifier = model_identifier("balanced", legacy_scoring, loaded.component_weights)
    raw = copy.deepcopy(loaded.raw)
    raw["scoring"]["model_version"] = legacy_identifier
    settings = Settings(root=loaded.root, raw=raw, universe=loaded.universe)

    errors, warnings = validate_settings(settings)

    assert not errors
    assert any("predates the current calculation policy" in warning for warning in warnings)


def test_v1_2_custom_profile_is_accepted_with_upgrade_warning():
    loaded = load_settings(Path.cwd())
    legacy_scoring = copy.deepcopy(loaded.raw["scoring"])
    legacy_scoring.pop("eligibility")
    legacy_scoring["calculation_version"] = "market-metrics-v1.2.0"
    legacy_identifier = model_identifier("balanced", legacy_scoring, loaded.component_weights)
    raw = copy.deepcopy(loaded.raw)
    raw["scoring"]["model_version"] = legacy_identifier
    settings = Settings(root=loaded.root, raw=raw, universe=loaded.universe)

    errors, warnings = validate_settings(settings)

    assert not errors
    assert any("predates the current calculation policy" in warning for warning in warnings)


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
    monkeypatch.setenv("SEC_USER_AGENT", "Stock Research Test test@example.org")
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


@pytest.mark.parametrize("failed_stage", [1, 2])
def test_personalization_stage_failure_leaves_prior_pair_unchanged(
    tmp_path, monkeypatch, failed_stage
):
    _project_config(tmp_path)
    expected = _seed_personalization(tmp_path)
    original = customization._stage_text
    calls = 0

    def fail_selected_stage(path, content):
        nonlocal calls
        calls += 1
        if calls == failed_stage:
            raise OSError("controlled staging failure")
        return original(path, content)

    monkeypatch.setattr(customization, "_stage_text", fail_selected_stage)

    with pytest.raises(customization.PersonalizationUpdateError, match="No active files changed"):
        customization.save_local_customization(
            tmp_path, **_personalization_kwargs(profile="growth")
        )

    _assert_personalization_bytes(tmp_path, expected)


@pytest.mark.parametrize("failed_backup", [1, 2])
def test_personalization_backup_failure_restores_prior_pair(
    tmp_path, monkeypatch, failed_backup
):
    _project_config(tmp_path)
    expected = _seed_personalization(tmp_path)
    original = customization._backup_active_file
    calls = 0

    def fail_selected_backup(path, backup):
        nonlocal calls
        calls += 1
        if calls == failed_backup:
            raise OSError("controlled backup failure")
        return original(path, backup)

    monkeypatch.setattr(customization, "_backup_active_file", fail_selected_backup)

    with pytest.raises(customization.PersonalizationUpdateError, match="Prior configuration restored"):
        customization.save_local_customization(
            tmp_path, **_personalization_kwargs(profile="growth")
        )

    _assert_personalization_bytes(tmp_path, expected)


@pytest.mark.parametrize("failed_replacement", [1, 2])
def test_personalization_replacement_failure_restores_prior_pair(
    tmp_path, monkeypatch, failed_replacement
):
    _project_config(tmp_path)
    expected = _seed_personalization(tmp_path)
    original = customization._install_staged_file
    calls = 0

    def fail_selected_replacement(staged, path):
        nonlocal calls
        calls += 1
        if calls == failed_replacement:
            raise OSError("controlled replacement failure")
        return original(staged, path)

    monkeypatch.setattr(customization, "_install_staged_file", fail_selected_replacement)

    with pytest.raises(customization.PersonalizationUpdateError, match="Prior configuration restored"):
        customization.save_local_customization(
            tmp_path, **_personalization_kwargs(profile="growth")
        )

    _assert_personalization_bytes(tmp_path, expected)


def test_first_personalization_failure_restores_absent_pair(tmp_path, monkeypatch):
    _project_config(tmp_path)
    original = customization._install_staged_file
    calls = 0

    def fail_second_replacement(staged, path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("controlled first-save failure")
        return original(staged, path)

    monkeypatch.setattr(customization, "_install_staged_file", fail_second_replacement)

    with pytest.raises(customization.PersonalizationUpdateError, match="Prior configuration restored"):
        customization.save_local_customization(tmp_path, **_personalization_kwargs())

    assert not (tmp_path / "config" / "preferences.local.toml").exists()
    assert not (tmp_path / "config" / "universe.local.csv").exists()
    assert list((tmp_path / "config").glob("universe.local.csv.failed.*"))


def test_personalization_reload_failure_restores_prior_pair(tmp_path, monkeypatch):
    _project_config(tmp_path)
    expected = _seed_personalization(tmp_path)

    def fail_reload(_root):
        raise ValueError("controlled reload failure")

    monkeypatch.setattr(customization, "_reload_local_customization", fail_reload)

    with pytest.raises(customization.PersonalizationUpdateError, match="Prior configuration restored"):
        customization.save_local_customization(
            tmp_path, **_personalization_kwargs(profile="growth")
        )

    _assert_personalization_bytes(tmp_path, expected)


def test_personalization_rollback_failure_preserves_recovery_backup(tmp_path, monkeypatch):
    _project_config(tmp_path)
    _seed_personalization(tmp_path)
    original_install = customization._install_staged_file
    install_calls = 0

    def fail_second_replacement(staged, path):
        nonlocal install_calls
        install_calls += 1
        if install_calls == 2:
            raise OSError("controlled replacement failure")
        return original_install(staged, path)

    def fail_restore(_backup, _path):
        raise OSError("controlled rollback failure")

    monkeypatch.setattr(customization, "_install_staged_file", fail_second_replacement)
    monkeypatch.setattr(customization, "_restore_backup_file", fail_restore)

    with pytest.raises(customization.PersonalizationUpdateError, match="RECOVERY REQUIRED") as exc:
        customization.save_local_customization(
            tmp_path, **_personalization_kwargs(profile="growth")
        )

    assert "preferences.local.toml" in str(exc.value)
    assert list((tmp_path / "config").glob("preferences.local.toml.bak*"))


@pytest.mark.parametrize("failed_backup", [1, 2])
def test_personalization_reset_failure_restores_prior_pair(tmp_path, monkeypatch, failed_backup):
    _project_config(tmp_path)
    expected = _seed_personalization(tmp_path)
    original = customization._backup_active_file
    calls = 0

    def fail_selected_backup(path, backup):
        nonlocal calls
        calls += 1
        if calls == failed_backup:
            raise OSError("controlled reset failure")
        return original(path, backup)

    monkeypatch.setattr(customization, "_backup_active_file", fail_selected_backup)

    with pytest.raises(customization.PersonalizationUpdateError, match="Prior configuration restored"):
        customization.reset_local_customization(tmp_path)

    _assert_personalization_bytes(tmp_path, expected)


def test_personalization_reset_moves_both_files_and_reloads_defaults(tmp_path):
    _project_config(tmp_path)
    _seed_personalization(tmp_path)

    backups = customization.reset_local_customization(tmp_path)

    assert len(backups) == 2
    assert all(path.is_file() for path in backups)
    assert not (tmp_path / "config" / "preferences.local.toml").exists()
    assert not (tmp_path / "config" / "universe.local.csv").exists()
    assert not load_settings(tmp_path).uses_local_preferences


def test_configure_reports_transaction_failure_without_traceback(tmp_path, monkeypatch, capsys):
    _project_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fail_save(*_args, **_kwargs):
        raise customization.PersonalizationUpdateError("controlled transaction failure")

    monkeypatch.setattr(cli, "save_local_customization", fail_save)
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
        universe_file=None,
        use_default_universe=False,
    )

    assert cli.command_configure(args) == 2
    assert "controlled transaction failure" in capsys.readouterr().err


def test_configure_reset_reports_transaction_failure_without_traceback(
    tmp_path, monkeypatch, capsys
):
    _project_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fail_reset(_root):
        raise customization.PersonalizationUpdateError("controlled reset transaction failure")

    monkeypatch.setattr(cli, "reset_local_customization", fail_reset)

    assert cli.command_configure(Namespace(reset=True)) == 2
    assert "controlled reset transaction failure" in capsys.readouterr().err


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
    assert warnings == ["Universes below 10 stocks cannot produce production percentiles"]
