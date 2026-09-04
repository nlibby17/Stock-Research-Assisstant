from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
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


@dataclass(frozen=True)
class HistoricalComparisonRun:
    """Stored run evidence needed to decide historical-comparison eligibility."""

    run_id: str
    status: str
    started_at: str
    as_of: str
    manifest: dict[str, Any] | None
    observed_universe_members: dict[str, tuple[str, str]]


@dataclass(frozen=True)
class HistoricalComparisonInputs:
    """Explicit inputs for one current-run and candidate-run comparison."""

    current_run_id: str
    candidate_run_id: str
    current: HistoricalComparisonRun | None
    candidate: HistoricalComparisonRun | None


@dataclass(frozen=True)
class HistoricalComparisonEligibility:
    eligible: bool
    reasons: tuple[str, ...]


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


def _manifest_universe_members(manifest: dict[str, Any]) -> dict[str, tuple[str, str]]:
    members = manifest.get("universe_members", [])
    if not isinstance(members, list):
        return {}
    return {
        str(member.get("ticker")): (
            str(member.get("company")),
            str(member.get("sector")),
        )
        for member in members
        if isinstance(member, dict)
        and member.get("ticker")
        and member.get("company")
        and member.get("sector")
    }


def evaluate_historical_comparison(
    inputs: HistoricalComparisonInputs,
) -> HistoricalComparisonEligibility:
    """Apply the complete stored-run comparison contract without database access."""
    current = inputs.current
    candidate = inputs.candidate
    if current is None or candidate is None:
        missing = inputs.current_run_id if current is None else inputs.candidate_run_id
        return HistoricalComparisonEligibility(False, (f"Unknown analysis run: {missing}",))

    reasons: list[str] = []
    if current.status != "completed":
        reasons.append("Current run is not complete")
    if candidate.status != "completed":
        reasons.append("Candidate run is not complete")
    if candidate.started_at >= current.started_at:
        reasons.append("Candidate run is not earlier than the current run")
    if candidate.as_of >= current.as_of:
        reasons.append("Runs do not represent different ordered market-data dates")

    for label, manifest in (
        ("Current", current.manifest),
        ("Candidate", candidate.manifest),
    ):
        status, manifest_reasons = validate_run_manifest(manifest)
        if status != REPRODUCIBILITY_STATUS:
            reasons.extend(f"{label} run: {reason}" for reason in manifest_reasons)

    if current.manifest and candidate.manifest:
        current_contract = current.manifest.get("calculation_contract_fingerprint")
        candidate_contract = candidate.manifest.get("calculation_contract_fingerprint")
        if current_contract != candidate_contract:
            reasons.append("Calculation contracts differ")
        for label, run in (("Current", current), ("Candidate", candidate)):
            expected = _manifest_universe_members(run.manifest)
            if not expected:
                reasons.append(f"{label} run has no recorded universe membership")
            elif run.observed_universe_members != expected:
                reasons.append(f"{label} run result membership does not match its manifest")

    return HistoricalComparisonEligibility(not reasons, tuple(dict.fromkeys(reasons)))
