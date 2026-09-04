from copy import deepcopy
from pathlib import Path

import pytest

from stockrank.config import load_settings
from stockrank.reproducibility import (
    RUN_MANIFEST_VERSION,
    HistoricalComparisonInputs,
    HistoricalComparisonRun,
    build_run_manifest,
    evaluate_historical_comparison,
    stable_fingerprint,
    validate_run_manifest,
)
from stockrank.storage import SCHEMA_VERSION


def comparison_manifest(
    *,
    contract_fingerprint: str = "calculation-contract",
    members: tuple[str, ...] = ("A",),
) -> dict:
    contract = {
        "version": "ranking-calculations-v1",
        "implementation_fingerprint": "implementation",
        "provider_name": "test",
        "provider_policy_fingerprint": "provider-policy",
        "selection_policy_fingerprint": "selection-policy",
        "model_version": "model-a",
        "calculation_version": "calculation-a",
        "scoring_policy_fingerprint": "scoring-policy",
        "universe_name": "universe-a",
        "universe_fingerprint": "universe-fingerprint",
    }
    manifest = {
        "manifest_version": RUN_MANIFEST_VERSION,
        "application_version": "test",
        "database_schema_version": SCHEMA_VERSION,
        "calculation_contract": contract,
        "calculation_contract_fingerprint": contract_fingerprint,
        "configuration_fingerprint": "configuration",
        "universe_members": [
            {"ticker": ticker, "company": ticker, "sector": "Test"} for ticker in members
        ],
        "environment": {},
    }
    if contract_fingerprint == "calculation-contract":
        manifest["calculation_contract_fingerprint"] = stable_fingerprint(contract)
    manifest["manifest_fingerprint"] = stable_fingerprint(manifest)
    return manifest


def comparison_run(
    run_id: str,
    *,
    status: str = "completed",
    started_at: str = "2026-01-02T12:00:00+00:00",
    as_of: str = "2026-01-02",
    manifest: dict | None = None,
    observed_members: dict[str, tuple[str, str]] | None = None,
) -> HistoricalComparisonRun:
    return HistoricalComparisonRun(
        run_id=run_id,
        status=status,
        started_at=started_at,
        as_of=as_of,
        manifest=comparison_manifest() if manifest is None else manifest,
        observed_universe_members=(
            {"A": ("A", "Test")} if observed_members is None else observed_members
        ),
    )


def comparison_inputs(
    *,
    current: HistoricalComparisonRun | None = None,
    candidate: HistoricalComparisonRun | None = None,
) -> HistoricalComparisonInputs:
    return HistoricalComparisonInputs(
        current_run_id="current",
        candidate_run_id="candidate",
        current=current or comparison_run("current"),
        candidate=candidate
        or comparison_run(
            "candidate",
            started_at="2026-01-01T12:00:00+00:00",
            as_of="2026-01-01",
        ),
    )


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


def test_historical_comparison_accepts_complete_ordered_matching_runs():
    result = evaluate_historical_comparison(comparison_inputs())

    assert result.eligible is True
    assert result.reasons == ()


@pytest.mark.parametrize(
    ("current", "candidate", "reason"),
    (
        (None, comparison_run("candidate"), "Unknown analysis run: current"),
        (comparison_run("current"), None, "Unknown analysis run: candidate"),
        (None, None, "Unknown analysis run: current"),
    ),
)
def test_historical_comparison_reports_the_first_missing_run(current, candidate, reason):
    inputs = HistoricalComparisonInputs(
        current_run_id="current",
        candidate_run_id="candidate",
        current=current,
        candidate=candidate,
    )

    result = evaluate_historical_comparison(inputs)

    assert result.eligible is False
    assert result.reasons == (reason,)


def test_historical_comparison_preserves_status_chronology_and_manifest_reason_order():
    current = comparison_run(
        "current",
        status="failed",
        started_at="2026-01-01T12:00:00+00:00",
        as_of="2026-01-01",
        manifest={},
    )
    candidate = comparison_run(
        "candidate",
        status="failed",
        started_at="2026-01-02T12:00:00+00:00",
        as_of="2026-01-01",
        manifest={},
    )

    result = evaluate_historical_comparison(comparison_inputs(current=current, candidate=candidate))

    assert result.eligible is False
    assert result.reasons == (
        "Current run is not complete",
        "Candidate run is not complete",
        "Candidate run is not earlier than the current run",
        "Runs do not represent different ordered market-data dates",
        "Current run: Formal run reproducibility manifest was not recorded",
        "Candidate run: Formal run reproducibility manifest was not recorded",
    )


def test_historical_comparison_preserves_contract_and_membership_reason_order():
    current_manifest = comparison_manifest()
    candidate_manifest = comparison_manifest(contract_fingerprint="different-contract")
    current = comparison_run("current", manifest=current_manifest, observed_members={})
    candidate = comparison_run(
        "candidate",
        started_at="2026-01-01T12:00:00+00:00",
        as_of="2026-01-01",
        manifest=candidate_manifest,
        observed_members={"B": ("B", "Test")},
    )

    result = evaluate_historical_comparison(comparison_inputs(current=current, candidate=candidate))

    assert result.eligible is False
    assert result.reasons == (
        "Candidate run: Calculation contract fingerprint does not match its stored content",
        "Calculation contracts differ",
        "Current run result membership does not match its manifest",
        "Candidate run result membership does not match its manifest",
    )


def test_historical_comparison_reports_missing_recorded_membership_after_manifest_validation():
    empty_manifest = comparison_manifest(members=())
    current = comparison_run("current", manifest=empty_manifest, observed_members={})
    candidate = comparison_run(
        "candidate",
        started_at="2026-01-01T12:00:00+00:00",
        as_of="2026-01-01",
        manifest=empty_manifest,
        observed_members={},
    )

    result = evaluate_historical_comparison(comparison_inputs(current=current, candidate=candidate))

    assert result.reasons == (
        "Current run: Exact universe membership is missing or invalid",
        "Candidate run: Exact universe membership is missing or invalid",
        "Current run has no recorded universe membership",
        "Candidate run has no recorded universe membership",
    )


def test_historical_comparison_deduplicates_repeated_reasons(monkeypatch):
    monkeypatch.setattr(
        "stockrank.reproducibility.validate_run_manifest",
        lambda manifest: ("limited", ["Repeated", "Repeated"]),
    )

    result = evaluate_historical_comparison(comparison_inputs())

    assert result.reasons == ("Current run: Repeated", "Candidate run: Repeated")
