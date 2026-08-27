from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stockrank.config import load_settings
from stockrank.data.sec import (
    SecClient,
    SecCompanyFacts,
    SecCompanyIdentity,
    SecConceptSpec,
    SecPayloadError,
    load_sec_concept_specs,
)
from stockrank.models import SecFiling

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"
IDENTITY = SecCompanyIdentity(
    cik="0001045810",
    name="NVIDIA CORP",
    ticker="NVDA",
    exchange="Nasdaq",
)
SPECS = (
    SecConceptSpec(
        canonical_name="revenue",
        period_type="duration",
        units=("USD",),
        members=(("us-gaap", "PrimaryRevenue"), ("us-gaap", "Revenues")),
    ),
    SecConceptSpec(
        canonical_name="assets",
        period_type="instant",
        units=("USD",),
        members=(("us-gaap", "Assets"),),
    ),
)


def test_project_revenue_map_prefers_broad_total_revenue_concept():
    settings = load_settings(Path(__file__).resolve().parents[1])
    revenue = next(
        spec
        for spec in load_sec_concept_specs(settings)
        if spec.canonical_name == "revenue"
    )
    assert revenue.members[:2] == (
        ("us-gaap", "Revenues"),
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    )


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append(url)
        return FakeResponse(self.payload)


def filing(accession, filed, accepted):
    return SecFiling(
        cik=IDENTITY.cik,
        ticker="NVDA",
        company_name=IDENTITY.name,
        accession_number=accession,
        form="10-K",
        base_form="10-K",
        is_amendment=False,
        filing_date=filed,
        report_date=date(2024, 12, 31),
        acceptance_datetime=accepted.isoformat(),
        accepted_at=accepted,
        availability_date=accepted.date(),
        availability_precision="timestamp",
        primary_document="annual.htm",
        filing_index_url="https://www.sec.gov/filing",
        primary_document_url="https://www.sec.gov/document",
        source_url="https://data.sec.gov/submissions/CIK0001045810.json",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def payload(revenue_value=100):
    original = {
        "start": "2024-01-01",
        "end": "2024-12-31",
        "val": 90,
        "accn": "0001045810-25-000010",
        "fy": 2024,
        "fp": "FY",
        "form": "10-K",
        "filed": "2025-02-20",
        "frame": "CY2024",
    }
    restated = {
        **original,
        "val": revenue_value,
        "accn": "0001045810-26-000020",
        "fy": 2025,
        "filed": "2026-02-20",
    }
    return {
        "cik": 1045810,
        "entityName": "NVIDIA CORP",
        "facts": {
            "us-gaap": {
                "PrimaryRevenue": {
                    "label": "Primary revenue",
                    "description": "Entity-wide revenue.",
                    "units": {"USD": [original, restated], "EUR": [restated]},
                },
                "Revenues": {
                    "label": "Revenue alias",
                    "description": "Lower-priority alias.",
                    "units": {"USD": [restated]},
                },
                "Assets": {
                    "label": "Assets",
                    "description": "Total assets.",
                    "units": {
                        "USD": [
                            {
                                "end": "2024-12-31",
                                "val": 500,
                                "accn": "0001045810-25-000010",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-20",
                                "frame": "CY2024Q4I",
                            }
                        ]
                    },
                },
            }
        },
    }


def make_adapter(tmp_path, value=100):
    session = FakeSession(payload(value))
    client = SecClient(
        user_agent="Personal Stock Research Assistant owner@example.org",
        cache_dir=tmp_path / "cache",
        session=session,
        sleep=lambda _: None,
    )
    return SecCompanyFacts(client, concept_specs=SPECS), session


def test_companyfacts_normalizes_units_contexts_and_filing_availability(tmp_path):
    adapter, session = make_adapter(tmp_path)
    original = filing(
        "0001045810-25-000010",
        date(2025, 2, 20),
        datetime(2025, 2, 20, 21, 5, tzinfo=UTC),
    )
    restated = filing(
        "0001045810-26-000020",
        date(2026, 2, 20),
        datetime(2026, 2, 20, 21, 10, tzinfo=UTC),
    )
    snapshot = adapter.fetch(
        IDENTITY,
        ticker="NVDA",
        since_date=date(2025, 1, 1),
        filings=(original, restated),
    )
    assert session.calls == [URL]
    assert len(snapshot.facts) == 4
    assert snapshot.present_concepts == ("revenue", "assets")
    assert snapshot.unmatched_accessions == 0
    primary = next(
        fact
        for fact in snapshot.facts
        if fact.accession_number == restated.accession_number
        and fact.concept == "PrimaryRevenue"
    )
    assert primary.value == Decimal(100)
    assert primary.unit == "USD"
    assert primary.start_date == date(2024, 1, 1)
    assert primary.fiscal_year == 2025
    assert primary.fiscal_period == "FY"
    assert primary.frame == "CY2024"
    assert primary.accepted_at == restated.accepted_at
    assert primary.availability_precision == "timestamp"


def test_effective_facts_handle_aliases_restatements_and_point_in_time(tmp_path):
    adapter, _ = make_adapter(tmp_path)
    original = filing(
        "0001045810-25-000010",
        date(2025, 2, 20),
        datetime(2025, 2, 20, 21, 5, tzinfo=UTC),
    )
    restated = filing(
        "0001045810-26-000020",
        date(2026, 2, 20),
        datetime(2026, 2, 20, 21, 10, tzinfo=UTC),
    )
    facts = adapter.fetch(
        IDENTITY,
        ticker="NVDA",
        since_date=date(2025, 1, 1),
        filings=(original, restated),
    ).facts
    effective = adapter.effective_facts(facts)
    revenue = next(fact for fact in effective if fact.canonical_name == "revenue")
    assert revenue.value == Decimal(100)
    assert revenue.concept == "PrimaryRevenue"

    before_restatement = adapter.effective_facts(
        facts,
        available_at=datetime(2025, 12, 31, 23, 59, tzinfo=UTC),
    )
    revenue = next(
        fact for fact in before_restatement if fact.canonical_name == "revenue"
    )
    assert revenue.value == Decimal(90)
    with pytest.raises(ValueError, match="timezone"):
        adapter.effective_facts(
            facts, available_at=datetime.fromisoformat("2025-01-01")
        )


def test_unknown_accession_uses_filed_date_precision(tmp_path):
    adapter, _ = make_adapter(tmp_path)
    snapshot = adapter.fetch(
        IDENTITY,
        ticker="NVDA",
        since_date=date(2026, 1, 1),
    )
    assert snapshot.unmatched_accessions == 1
    assert all(fact.accepted_at is None for fact in snapshot.facts)
    assert all(fact.availability_precision == "date" for fact in snapshot.facts)


def test_missing_configured_concept_remains_missing(tmp_path):
    missing_spec = SecConceptSpec(
        canonical_name="not_reported",
        period_type="duration",
        units=("USD",),
        members=(("us-gaap", "ConceptThatDoesNotExist"),),
    )
    session = FakeSession(payload())
    client = SecClient(
        user_agent="Personal Stock Research Assistant owner@example.org",
        cache_dir=tmp_path / "cache",
        session=session,
        sleep=lambda _: None,
    )
    snapshot = SecCompanyFacts(client, concept_specs=(missing_spec,)).fetch(
        IDENTITY, ticker="NVDA", since_date=date(2025, 1, 1)
    )
    assert snapshot.facts == ()
    assert snapshot.present_concepts == ()


def test_companyfacts_rejects_invalid_period_shape_and_values(tmp_path):
    bad_payload = payload()
    bad_payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["start"] = (
        "2024-01-01"
    )
    session = FakeSession(bad_payload)
    client = SecClient(
        user_agent="Personal Stock Research Assistant owner@example.org",
        cache_dir=tmp_path / "cache",
        session=session,
        sleep=lambda _: None,
    )
    adapter = SecCompanyFacts(client, concept_specs=SPECS)
    with pytest.raises(SecPayloadError, match="instant fact"):
        adapter.fetch(IDENTITY, ticker="NVDA", since_date=date(2025, 1, 1))

    bad_payload = payload(revenue_value="not-a-number")
    session = FakeSession(bad_payload)
    client = SecClient(
        user_agent="Personal Stock Research Assistant owner@example.org",
        cache_dir=tmp_path / "other-cache",
        session=session,
        sleep=lambda _: None,
    )
    adapter = SecCompanyFacts(client, concept_specs=SPECS)
    with pytest.raises(SecPayloadError, match="nonnumeric"):
        adapter.fetch(IDENTITY, ticker="NVDA", since_date=date(2025, 1, 1))


def test_companyfacts_deduplicates_equal_contexts_and_rejects_conflicts(tmp_path):
    duplicate_payload = payload()
    rows = duplicate_payload["facts"]["us-gaap"]["PrimaryRevenue"]["units"]["USD"]
    rows.append(dict(rows[0]))
    session = FakeSession(duplicate_payload)
    client = SecClient(
        user_agent="Personal Stock Research Assistant owner@example.org",
        cache_dir=tmp_path / "cache",
        session=session,
        sleep=lambda _: None,
    )
    adapter = SecCompanyFacts(client, concept_specs=SPECS)
    snapshot = adapter.fetch(IDENTITY, ticker="NVDA", since_date=date(2025, 1, 1))
    assert len(snapshot.facts) == 4

    duplicate_payload = payload()
    rows = duplicate_payload["facts"]["us-gaap"]["PrimaryRevenue"]["units"]["USD"]
    conflicting = dict(rows[0])
    conflicting["val"] = 91
    rows.append(conflicting)
    session = FakeSession(duplicate_payload)
    client = SecClient(
        user_agent="Personal Stock Research Assistant owner@example.org",
        cache_dir=tmp_path / "conflict-cache",
        session=session,
        sleep=lambda _: None,
    )
    adapter = SecCompanyFacts(client, concept_specs=SPECS)
    with pytest.raises(SecPayloadError, match="conflicting values"):
        adapter.fetch(IDENTITY, ticker="NVDA", since_date=date(2025, 1, 1))
