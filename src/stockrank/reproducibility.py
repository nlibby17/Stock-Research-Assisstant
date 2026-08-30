from __future__ import annotations

import hashlib
import json
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from stockrank.config import Settings
from stockrank.version import APP_VERSION

RUN_MANIFEST_VERSION = "run-reproducibility-v1"
CALCULATION_CONTRACT_VERSION = "ranking-calculations-v1"
REPRODUCIBILITY_STATUS = "recorded"
CALCULATION_IMPLEMENTATION_FILES = (
    "freshness.py",
    "metrics.py",
    "pipeline.py",
    "price_integrity.py",
    "scoring.py",
    "data/yfinance_provider.py",
)


def stable_fingerprint(value: Any) -> str:
    """Return a stable full-length fingerprint for a JSON-compatible value."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def calculation_implementation_fingerprint() -> str:
    package_root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for relative_path in CALCULATION_IMPLEMENTATION_FILES:
        digest.update(relative_path.encode())
        source = (package_root / relative_path).read_text(encoding="utf-8")
        digest.update(source.replace("\r\n", "\n").encode())
    return digest.hexdigest()


def build_run_manifest(settings: Settings, *, provider_name: str, schema_version: int) -> dict[str, Any]:
    """Capture the calculation contract and environment needed to interpret a run."""
    universe_members = [
        {"ticker": value.ticker, "company": value.company, "sector": value.sector}
        for value in settings.universe
    ]
    provider_policy = settings.raw["provider"]
    selection_policy = {
        key: settings.raw["app"][key]
        for key in (
            "timezone",
            "top_candidate_limit",
            "minimum_candidate_score",
            "minimum_overall_coverage",
        )
    }
    calculation_contract = {
        "version": CALCULATION_CONTRACT_VERSION,
        "implementation_fingerprint": calculation_implementation_fingerprint(),
        "provider_name": provider_name,
        "provider_policy_fingerprint": stable_fingerprint(provider_policy),
        "selection_policy_fingerprint": stable_fingerprint(selection_policy),
        "model_version": settings.model_version,
        "calculation_version": str(settings.raw["scoring"]["calculation_version"]),
        "scoring_policy_fingerprint": settings.scoring_fingerprint,
        "universe_name": str(settings.raw["universe"]["name"]),
        "universe_fingerprint": settings.universe_fingerprint,
    }
    manifest = {
        "manifest_version": RUN_MANIFEST_VERSION,
        "application_version": APP_VERSION,
        "database_schema_version": schema_version,
        "calculation_contract": calculation_contract,
        "calculation_contract_fingerprint": stable_fingerprint(calculation_contract),
        "configuration_fingerprint": stable_fingerprint(settings.raw),
        "universe_members": universe_members,
        "environment": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "packages": {
                name: _package_version(name)
                for name in ("requests", "streamlit", "yfinance")
            },
        },
    }
    manifest["manifest_fingerprint"] = stable_fingerprint(manifest)
    return manifest


def validate_run_manifest(manifest: dict[str, Any] | None) -> tuple[str, list[str]]:
    """Classify whether a stored manifest has the complete current contract."""
    if not manifest:
        return "legacy_limited", ["Formal run reproducibility manifest was not recorded"]
    reasons: list[str] = []
    if manifest.get("manifest_version") != RUN_MANIFEST_VERSION:
        reasons.append("Run manifest version is missing or unsupported")
    for field in (
        "application_version",
        "database_schema_version",
        "configuration_fingerprint",
        "environment",
    ):
        if manifest.get(field) in (None, ""):
            reasons.append(f"Run manifest field is missing: {field}")
    members = manifest.get("universe_members")
    valid_members = (
        isinstance(members, list)
        and bool(members)
        and all(
            isinstance(member, dict)
            and member.get("ticker")
            and member.get("company")
            and member.get("sector")
            for member in members
        )
        and len({member["ticker"] for member in members}) == len(members)
    )
    if not valid_members:
        reasons.append("Exact universe membership is missing or invalid")
    contract = manifest.get("calculation_contract")
    if not isinstance(contract, dict):
        reasons.append("Calculation contract is missing")
    else:
        required = {
            "version",
            "implementation_fingerprint",
            "provider_name",
            "provider_policy_fingerprint",
            "selection_policy_fingerprint",
            "model_version",
            "calculation_version",
            "scoring_policy_fingerprint",
            "universe_name",
            "universe_fingerprint",
        }
        missing = sorted(required - contract.keys())
        if missing:
            reasons.append("Calculation contract is missing: " + ", ".join(missing))
        recorded_contract = manifest.get("calculation_contract_fingerprint")
        if recorded_contract != stable_fingerprint(contract):
            reasons.append("Calculation contract fingerprint does not match its stored content")
    recorded_manifest = manifest.get("manifest_fingerprint")
    unsigned = dict(manifest)
    unsigned.pop("manifest_fingerprint", None)
    if recorded_manifest != stable_fingerprint(unsigned):
        reasons.append("Run manifest fingerprint does not match its stored content")
    return (REPRODUCIBILITY_STATUS, []) if not reasons else ("limited", reasons)
