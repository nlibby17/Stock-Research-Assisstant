from __future__ import annotations

import csv
import io

from stockrank.presentation import ranking_change_summary, rankings_csv


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
    assert rows[0]["Growth score"] == "70"
