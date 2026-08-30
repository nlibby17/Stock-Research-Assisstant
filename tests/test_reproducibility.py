from copy import deepcopy
from pathlib import Path

from stockrank.config import load_settings
from stockrank.reproducibility import build_run_manifest, validate_run_manifest
from stockrank.storage import SCHEMA_VERSION


def test_run_manifest_records_and_verifies_calculation_contract():
    settings = load_settings(Path(__file__).resolve().parents[1])
    manifest = build_run_manifest(
        settings,
        provider_name="yfinance",
        schema_version=SCHEMA_VERSION,
    )

    status, reasons = validate_run_manifest(manifest)

    assert status == "recorded"
    assert reasons == []
    assert manifest["calculation_contract"]["model_version"] == settings.model_version
    assert manifest["calculation_contract"]["universe_fingerprint"]
    assert len(manifest["universe_members"]) == len(settings.universe)


def test_run_manifest_detects_content_changes():
    settings = load_settings(Path(__file__).resolve().parents[1])
    manifest = build_run_manifest(
        settings,
        provider_name="yfinance",
        schema_version=SCHEMA_VERSION,
    )
    tampered = deepcopy(manifest)
    tampered["calculation_contract"]["model_version"] = "silently-changed"

    status, reasons = validate_run_manifest(tampered)

    assert status == "limited"
    assert any("fingerprint" in reason for reason in reasons)
