from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from stockrank.provider_evidence import (
    ProductionResultEvidence,
    ProductionRunEvidence,
    SecFormulaContractEvidence,
    evaluate_promotion_evidence,
)

AS_OF = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
MARKET_DATE = date(2026, 9, 3)
SUPPORTED_MANIFEST = {
    "contract_version": "sec-formula-contract-v1",
    "semantic_version": "sec-financials-v1.1.0",
    "concept_policy_fingerprint": "concept-current",
    "fingerprint": "formula-current",
}


def production_run(**changes) -> ProductionRunEvidence:
    value = ProductionRunEvidence(
        run_id="analysis-1",
        status="completed",
        provider="yfinance",
        universe_name="test-universe",
        completed_at=AS_OF - timedelta(minutes=5),
        as_of=MARKET_DATE,
        warnings=(),
    )
    return replace(value, **changes)


def production_results(*dates: date | None) -> tuple[ProductionResultEvidence, ...]:
    values = dates or (MARKET_DATE, MARKET_DATE)
    return tuple(
        ProductionResultEvidence(ticker=ticker, price_as_of=price_date)
        for ticker, price_date in zip(("AAA", "BBB"), values, strict=True)
    )


def formula_contracts(
    *,
    aaa_manifest=SUPPORTED_MANIFEST,
    bbb_manifest=SUPPORTED_MANIFEST,
    aaa_version: str | None = "sec-financials-v1.1.0",
    bbb_version: str | None = "sec-financials-v1.1.0",
) -> tuple[SecFormulaContractEvidence, ...]:
    return (
        SecFormulaContractEvidence("AAA", aaa_version, aaa_manifest),
        SecFormulaContractEvidence("BBB", bbb_version, bbb_manifest),
    )


def evaluate(**changes):
    values = {
        "full_universe": True,
        "comparison_status": "complete",
        "comparison_as_of": AS_OF,
        "stale_rows": 0,
        "production_run": production_run(),
        "production_results": production_results(),
        "expected_provider": "yfinance",
        "expected_universe_name": "test-universe",
        "expected_tickers": frozenset({"AAA", "BBB"}),
        "formula_contract_evidence": formula_contracts(),
        "supported_formula_version": "sec-financials-v1.1.0",
        "supported_formula_manifest": SUPPORTED_MANIFEST,
        "max_link_age_hours": 6,
    }
    values.update(changes)
    return evaluate_promotion_evidence(**values)


def test_complete_consistent_supported_contract_qualifies():
    result = evaluate()

    assert result.qualified is True
    assert result.analysis_run_id == "analysis-1"
    assert result.evidence_date == MARKET_DATE
    assert result.reason == (
        "Qualified: complete full-universe comparison linked to a consistent "
        "production market-data date and supported SEC formula contract"
    )
    assert result.formula_contracts == (
        {
            "formula_version": "sec-financials-v1.1.0",
            "formula_manifest": SUPPORTED_MANIFEST,
        },
    )


@pytest.mark.parametrize(
    ("changes", "expected_reason"),
    (
        (
            {"full_universe": False},
            "Partial-universe comparisons do not qualify as promotion evidence",
        ),
        ({"production_run": None}, "No production analysis run exists"),
        (
            {"production_run": production_run(status="failed")},
            "Latest production analysis run is failed, not completed",
        ),
        (
            {"production_run": production_run(provider="other")},
            "Latest analysis provider is other, not yfinance",
        ),
        (
            {"production_run": production_run(universe_name="other")},
            "Latest analysis used a different universe version",
        ),
        (
            {"production_run": production_run(completed_at=None)},
            "Latest production analysis has no completion time",
        ),
        (
            {
                "production_run": production_run(
                    warnings=("Price refresh failed for AAA; using cache",)
                )
            },
            "Linked production run used cached prices after a refresh failure",
        ),
        (
            {"production_run": production_run(completed_at=AS_OF + timedelta(seconds=1))},
            "Latest production analysis completed after this comparison",
        ),
        (
            {"production_run": production_run(completed_at=AS_OF - timedelta(hours=7))},
            "Latest production analysis is too old to link safely (>6 hours)",
        ),
        (
            {
                "production_results": (
                    ProductionResultEvidence("AAA", MARKET_DATE),
                    ProductionResultEvidence("CCC", MARKET_DATE),
                )
            },
            "Linked production run does not contain the exact universe",
        ),
        (
            {"production_results": production_results(MARKET_DATE, None)},
            "Linked production run has missing price dates",
        ),
        (
            {
                "production_results": production_results(
                    MARKET_DATE, MARKET_DATE - timedelta(days=1)
                )
            },
            "Linked production run has mixed market-data dates",
        ),
        (
            {"production_run": production_run(as_of=MARKET_DATE - timedelta(days=1))},
            "Production run as-of date does not match its price data",
        ),
        (
            {"formula_contract_evidence": formula_contracts(bbb_manifest=None)},
            "Missing SEC formula contract for 1/2 comparison securities: BBB",
        ),
        (
            {
                "formula_contract_evidence": formula_contracts(
                    bbb_manifest={**SUPPORTED_MANIFEST, "fingerprint": "other"}
                )
            },
            "Mixed SEC formula contracts across comparison securities: 2 distinct contracts",
        ),
        (
            {
                "formula_contract_evidence": formula_contracts(
                    aaa_version="sec-financials-v1.0.1",
                    bbb_version="sec-financials-v1.0.1",
                )
            },
            "Unsupported SEC formula contract: sec-financials-v1.0.1",
        ),
        ({"stale_rows": 2}, "Comparison contains 2 stale provider rows"),
        (
            {"comparison_status": "failed", "stale_rows": 0},
            "Comparison rows are incomplete",
        ),
    ),
)
def test_every_nonqualification_reason_has_stable_precedence(changes, expected_reason):
    inputs = {"stale_rows": 4, "comparison_status": "failed"}
    inputs.update(changes)
    result = evaluate(**inputs)

    assert result.qualified is False
    assert result.reason == expected_reason


def test_formula_reason_precedence_is_missing_then_mixed_then_unsupported():
    unsupported = {**SUPPORTED_MANIFEST, "fingerprint": "unsupported"}

    missing = evaluate(
        formula_contract_evidence=formula_contracts(
            aaa_manifest=None,
            bbb_manifest=unsupported,
            bbb_version="sec-financials-v1.0.1",
        )
    )
    mixed = evaluate(
        formula_contract_evidence=formula_contracts(
            bbb_manifest=unsupported,
            bbb_version="sec-financials-v1.0.1",
        )
    )
    unsupported_only = evaluate(
        formula_contract_evidence=formula_contracts(
            aaa_manifest=unsupported,
            bbb_manifest=unsupported,
        )
    )

    assert missing.reason.startswith("Missing SEC formula contract")
    assert mixed.reason.startswith("Mixed SEC formula contracts")
    assert unsupported_only.reason == "Unsupported SEC formula contract: sec-financials-v1.1.0"


def test_contract_set_is_canonical_and_preserves_actual_legacy_manifest():
    legacy = {"version": "sec-financials-v1.0.0", "fingerprint": "legacy"}

    result = evaluate(
        formula_contract_evidence=(
            SecFormulaContractEvidence("BBB", "sec-financials-v1.0.0", legacy),
            SecFormulaContractEvidence("AAA", "sec-financials-v1.0.0", legacy),
        )
    )

    assert result.formula_contracts == (
        {
            "formula_version": "sec-financials-v1.0.0",
            "formula_manifest": legacy,
        },
    )


def test_duplicate_formula_contract_ticker_is_rejected():
    with pytest.raises(ValueError, match="Duplicate SEC formula contract evidence for AAA"):
        evaluate(
            formula_contract_evidence=(
                SecFormulaContractEvidence("AAA", "sec-financials-v1.1.0", SUPPORTED_MANIFEST),
                SecFormulaContractEvidence("AAA", "sec-financials-v1.1.0", SUPPORTED_MANIFEST),
            )
        )
