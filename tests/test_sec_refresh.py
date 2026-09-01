from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from stockrank.data.sec import SecConceptSpec
from stockrank.models import SecCompanyFactsRefreshState, SecFiling
from stockrank.sec_refresh import (
    CompanyFactsRefreshPolicy,
    companyfacts_config_fingerprint,
    decide_companyfacts_refresh,
    filing_fingerprint,
    identity_fingerprint,
    latest_filing_at,
)

NOW = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
POLICY = CompanyFactsRefreshPolicy()


def make_filing(accession: str, accepted_at: datetime) -> SecFiling:
    return SecFiling(
        cik="0001045810",
        ticker="NVDA",
        company_name="NVIDIA CORP",
        accession_number=accession,
        form="10-Q",
        base_form="10-Q",
        is_amendment=False,
        filing_date=accepted_at.date(),
        report_date=date(2026, 6, 30),
        acceptance_datetime=accepted_at.isoformat(),
        accepted_at=accepted_at,
        availability_date=accepted_at.date(),
        availability_precision="timestamp",
        primary_document="quarter.htm",
        filing_index_url="https://www.sec.gov/filing",
        primary_document_url="https://www.sec.gov/document",
        source_url="https://data.sec.gov/submissions/CIK0001045810.json",
        fetched_at=NOW,
    )


def state(*, refreshed_at: datetime = NOW - timedelta(hours=24)):
    return SecCompanyFactsRefreshState(
        ticker="NVDA",
        identity_fingerprint="identity",
        filing_fingerprint="filings",
        config_fingerprint="config",
        last_successful_refresh_at=refreshed_at,
        latest_filing_at=NOW - timedelta(days=30),
        unmatched_accessions=0,
        last_refresh_reason="initial",
    )


def decide(**overrides):
    values = {
        "now": NOW,
        "force": False,
        "has_local_facts": True,
        "state": state(),
        "current_identity_fingerprint": "identity",
        "current_filing_fingerprint": "filings",
        "current_config_fingerprint": "config",
        "current_latest_filing_at": NOW - timedelta(days=30),
        "policy": POLICY,
    }
    values.update(overrides)
    return decide_companyfacts_refresh(**values)


def test_refresh_decision_reuses_unchanged_local_facts():
    decision = decide()
    assert decision.refresh is False
    assert decision.reason == "unchanged filings; reused local facts"


def test_refresh_decision_covers_force_missing_state_and_changed_inputs():
    assert decide(force=True).reason == "forced refresh"
    assert decide(has_local_facts=False).reason == "missing local facts"
    assert decide(state=None).reason == "initialize adaptive refresh state"
    assert decide(current_identity_fingerprint="new").reason == "SEC identity changed"
    assert decide(current_config_fingerprint="new").reason == (
        "Company Facts configuration changed"
    )
    changed = decide(current_filing_fingerprint="new")
    assert changed.reason == "new or changed SEC filing"
    assert changed.bypass_raw_cache is True


def test_recent_filing_follow_up_waits_for_retry_interval():
    recent = NOW - timedelta(hours=12)
    too_soon = decide(
        state=state(refreshed_at=NOW - timedelta(hours=2)),
        current_latest_filing_at=recent,
    )
    assert too_soon.refresh is False
    follow_up = decide(
        state=state(refreshed_at=NOW - timedelta(hours=7)),
        current_latest_filing_at=recent,
    )
    assert follow_up.reason == "recent filing follow-up"
    assert follow_up.bypass_raw_cache is True


def test_periodic_safety_refresh_occurs_after_seven_days():
    decision = decide(state=state(refreshed_at=NOW - timedelta(days=7)))
    assert decision.reason == "periodic safety refresh"
    assert decision.bypass_raw_cache is True


@pytest.mark.parametrize(
    ("refreshed_at", "reason"),
    [
        (NOW.replace(tzinfo=None), "invalid refresh timestamp"),
        (NOW + timedelta(minutes=6), "future refresh timestamp"),
    ],
)
def test_invalid_refresh_state_timestamp_forces_refresh(refreshed_at, reason):
    decision = decide(state=state(refreshed_at=refreshed_at))

    assert decision.refresh is True
    assert reason in decision.reason
    assert decision.bypass_raw_cache is True


@pytest.mark.parametrize(
    ("latest_filing", "reason"),
    [
        (NOW.replace(tzinfo=None), "invalid latest filing timestamp"),
        (NOW + timedelta(minutes=6), "future latest filing timestamp"),
    ],
)
def test_invalid_latest_filing_timestamp_forces_refresh(latest_filing, reason):
    decision = decide(current_latest_filing_at=latest_filing)

    assert decision.refresh is True
    assert reason in decision.reason
    assert decision.bypass_raw_cache is True


@pytest.mark.parametrize(
    ("latest_filing", "reason"),
    [
        (NOW.replace(tzinfo=None), "invalid stored latest filing timestamp"),
        (NOW + timedelta(minutes=6), "future stored latest filing timestamp"),
    ],
)
def test_invalid_stored_latest_filing_timestamp_forces_refresh(latest_filing, reason):
    invalid_state = replace(state(), latest_filing_at=latest_filing)

    decision = decide(state=invalid_state)

    assert decision.refresh is True
    assert reason in decision.reason
    assert decision.bypass_raw_cache is True


def test_small_refresh_clock_skew_is_tolerated():
    decision = decide(
        state=state(refreshed_at=NOW + timedelta(minutes=5)),
        current_latest_filing_at=NOW + timedelta(minutes=5),
    )

    assert decision.refresh is False


def test_fingerprints_and_latest_filing_are_stable_and_sensitive():
    first = make_filing("0001045810-26-000001", NOW - timedelta(days=1))
    second = make_filing("0001045810-26-000002", NOW)
    assert identity_fingerprint(["2", "1", "1"]) == identity_fingerprint(["1", "2"])
    assert filing_fingerprint([first, second]) == filing_fingerprint([second, first])
    assert filing_fingerprint([first]) != filing_fingerprint([first, second])
    assert latest_filing_at([first, second]) == NOW

    concept = SecConceptSpec(
        canonical_name="revenue",
        period_type="duration",
        units=("USD",),
        members=(("us-gaap", "Revenues"),),
    )
    baseline = companyfacts_config_fingerprint(
        history_years=5, forms=("10-K", "10-Q"), concepts=(concept,)
    )
    assert baseline == companyfacts_config_fingerprint(
        history_years=5, forms=("10-Q", "10-K"), concepts=(concept,)
    )
    assert baseline != companyfacts_config_fingerprint(
        history_years=6, forms=("10-K", "10-Q"), concepts=(concept,)
    )
