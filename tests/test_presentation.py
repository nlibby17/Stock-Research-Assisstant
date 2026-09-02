from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime

import pytest

from stockrank.models import SecFiling
from stockrank.presentation import (
    candidate_policy_summary,
    filings_for_completed_run,
    no_candidate_explanation,
    ranking_change_summary,
    rankings_csv,
    relative_status_label,
    score_breakdown,
)


def _filing(
    accession: str,
    *,
    accepted_at: datetime | None,
    availability_date: date,
    precision: str = "timestamp",
) -> SecFiling:
    return SecFiling(
        cik="0000000001",
        ticker="AAA",
        company_name="AAA Company",
        accession_number=accession,
        form="10-Q",
        base_form="10-Q",
        is_amendment=False,
        filing_date=availability_date,
        report_date=date(2026, 3, 31),
        acceptance_datetime=accepted_at.isoformat() if accepted_at else None,
        accepted_at=accepted_at,
        availability_date=availability_date,
        availability_precision=precision,
        primary_document="aaa.htm",
        filing_index_url=f"https://example.test/{accession}",
        primary_document_url=None,
        source_url="https://example.test/submissions",
        fetched_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


STORED_APP_POLICY = {
    "minimum_candidate_score": 55.0,
    "minimum_overall_coverage": 0.6,
}
STORED_ELIGIBILITY_POLICY = {
    "minimum_latest_price": 1.0,
    "minimum_average_dollar_volume_20d": 1_000_000.0,
}


def _result(
    ticker: str,
    rank: int,
    score: float,
    *,
    eligible: bool = True,
    company: str | None = None,
) -> dict:
    return {
        "rank": rank,
        "ticker": ticker,
        "company": company or f"{ticker} Company",
        "sector": "Industrials",
        "latest_price": 100.0 + rank,
        "price_as_of": "2026-08-28",
        "overall_score": score,
        "overall_coverage": 0.8,
        "eligible": eligible,
        "recommendation": "Worth further research",
        "component_scores": {
            "growth": score,
            "valuation": score - 1,
            "quality": score - 2,
            "momentum": score - 3,
            "risk": score - 4,
        },
        "component_coverage": {
            "growth": 1.0,
            "valuation": 0.8,
            "quality": 0.6,
            "momentum": 0.4,
            "risk": 0.2,
        },
    }


def test_ranking_change_summary_identifies_entries_exits_and_movers():
    previous = [_result("AAA", 1, 70), _result("BBB", 2, 65), _result("CCC", 3, 60)]
    current = [_result("BBB", 1, 68), _result("CCC", 2, 60.5), _result("AAA", 3, 67)]

    changes = ranking_change_summary(current, previous, current_limit=2, score_threshold=1)

    assert [row["Ticker"] for row in changes["new_candidates"]] == ["CCC"]
    assert [row["Ticker"] for row in changes["exited_candidates"]] == ["AAA"]
    assert changes["rank_gainers"][0] == {
        "Ticker": "BBB",
        "Previous rank": 2,
        "Current rank": 1,
        "Rank change": 1,
    }
    assert changes["rank_decliners"][0]["Ticker"] == "AAA"
    assert [row["Ticker"] for row in changes["score_changes"]] == ["AAA", "BBB"]


def test_rankings_csv_is_excel_friendly_and_flat():
    payload = rankings_csv([_result("AAA", 1, 70, company="Alpha, Incorporated")])

    assert payload.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    assert len(rows) == 1
    assert rows[0]["Company"] == "Alpha, Incorporated"
    assert rows[0]["Eligible"] == "yes"
    assert rows[0]["Eligibility notes"] == ""
    assert rows[0]["Growth score"] == "70"
    assert rows[0]["Relative status"] == "Above-average relative score"
    assert rows[0]["Growth coverage percent"] == "100.0"
    assert rows[0]["Risk coverage percent"] == "20.0"


def test_legacy_recommendation_text_is_presented_as_universe_relative():
    assert relative_status_label("Strong candidate") == "High relative score"
    assert relative_status_label("Insufficient coverage") == "Insufficient coverage"


def test_score_breakdown_uses_effective_coverage_adjusted_weights():
    result = _result("AAA", 1, 70)
    component_weights = {
        "growth": 0.25,
        "valuation": 0.20,
        "quality": 0.25,
        "momentum": 0.20,
        "risk": 0.10,
    }

    assert score_breakdown(result, component_weights) == (
        "Growth 70.0 × 38% · Valuation 69.0 × 24% · Quality 68.0 × 23% · "
        "Momentum 67.0 × 12% · Risk 66.0 × 3%"
    )


def test_filing_disclosure_requires_aware_recorded_completion_cutoff():
    filing = _filing(
        "before",
        accepted_at=datetime(2026, 5, 20, 12, tzinfo=UTC),
        availability_date=date(2026, 5, 20),
    )
    naive_cutoff = datetime(2026, 5, 20, 13, tzinfo=UTC).replace(tzinfo=None)

    for cutoff in (None, naive_cutoff):
        disclosure = filings_for_completed_run((filing,), cutoff)
        assert disclosure.filings == ()
        assert "timezone-aware completion timestamp" in disclosure.limitation


def test_filing_disclosure_respects_before_at_and_after_timestamp_cutoff():
    accepted_at = datetime(2026, 5, 20, 12, tzinfo=UTC)
    filing = _filing(
        "filing",
        accepted_at=accepted_at,
        availability_date=date(2026, 5, 20),
    )

    before = filings_for_completed_run(
        (filing,), datetime(2026, 5, 20, 11, 59, tzinfo=UTC)
    )
    at = filings_for_completed_run((filing,), accepted_at)
    after = filings_for_completed_run(
        (filing,), datetime(2026, 5, 20, 12, 1, tzinfo=UTC)
    )

    assert before.filings == ()
    assert at.filings == (filing,)
    assert after.filings == (filing,)
    assert at.limitation is None


def test_filing_disclosure_uses_date_for_date_only_availability():
    filing = _filing(
        "date-only",
        accepted_at=None,
        availability_date=date(2026, 5, 20),
        precision="date",
    )

    before = filings_for_completed_run(
        (filing,), datetime(2026, 5, 19, 23, 59, tzinfo=UTC)
    )
    on_date = filings_for_completed_run(
        (filing,), datetime(2026, 5, 20, 0, 0, tzinfo=UTC)
    )

    assert before.filings == ()
    assert on_date.filings == (filing,)


@pytest.mark.parametrize(
    ("updates", "expected_failure"),
    [
        ({"overall_score": 54.9}, "score 1"),
        ({"overall_coverage": 0.59}, "coverage 1"),
        ({"latest_price": 0.99}, "price 1"),
        ({"metrics": {"average_dollar_volume_20d": 999_999.0}}, "liquidity 1"),
        (
            {
                "overall_score": 54.9,
                "overall_coverage": 0.59,
                "latest_price": 0.99,
                "metrics": {"average_dollar_volume_20d": 999_999.0},
            },
            "score 1, coverage 1, price 1, liquidity 1",
        ),
    ],
)
def test_no_candidate_explanation_covers_each_stored_rule(updates, expected_failure):
    result = {
        "eligible": False,
        "overall_score": 60.0,
        "overall_coverage": 0.8,
        "latest_price": 10.0,
        "metrics": {"average_dollar_volume_20d": 2_000_000.0},
    }
    result.update(updates)

    explanation = no_candidate_explanation(
        [result], STORED_APP_POLICY, STORED_ELIGIBILITY_POLICY
    )

    assert "all stored candidate eligibility rules" in explanation
    assert expected_failure in explanation
    assert candidate_policy_summary(
        STORED_APP_POLICY, STORED_ELIGIBILITY_POLICY
    ) in explanation


def test_no_candidate_explanation_does_not_substitute_current_policy_for_legacy_run():
    explanation = no_candidate_explanation([], {}, {})

    assert "legacy run" in explanation
    assert "current settings are not substituted" in explanation
