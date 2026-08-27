from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from stockrank.data.sec import (
    SecClient,
    SecCompanyIdentity,
    SecPayloadError,
    SecSubmissions,
)

ROOT_URL = "https://data.sec.gov/submissions/CIK0001045810.json"
HISTORY_URL = "https://data.sec.gov/submissions/CIK0001045810-submissions-001.json"
IDENTITY = SecCompanyIdentity(
    cik="0001045810",
    name="NVIDIA CORP",
    ticker="NVDA",
    exchange="Nasdaq",
)


def columnar(rows):
    columns = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "form",
        "primaryDocument",
    )
    return {column: [row.get(column, "") for row in rows] for column in columns}


RECENT_ROWS = [
    {
        "accessionNumber": "0001045810-26-000052",
        "filingDate": "2026-05-20",
        "reportDate": "2026-04-26",
        "acceptanceDateTime": "2026-05-20T16:06:13.000Z",
        "form": "10-Q",
        "primaryDocument": "nvda-20260426.htm",
    },
    {
        "accessionNumber": "0001045810-26-000060",
        "filingDate": "2026-06-01",
        "reportDate": "2026-04-26",
        "acceptanceDateTime": "2026-06-01T09:30:00-04:00",
        "form": "10-Q/A",
        "primaryDocument": "nvda-20260426x10qa.htm",
    },
    {
        "accessionNumber": "0001045810-26-000061",
        "filingDate": "2026-06-02",
        "reportDate": "2026-06-02",
        "acceptanceDateTime": "2026-06-02T12:00:00Z",
        "form": "8-K",
        "primaryDocument": "nvda-8k.htm",
    },
]

HISTORY_ROWS = [
    {
        "accessionNumber": "0001045810-25-000010",
        "filingDate": "2025-02-26",
        "reportDate": "2025-01-26",
        "acceptanceDateTime": "2025-02-26T16:15:00",
        "form": "10-K",
        "primaryDocument": "nvda-20250126.htm",
    },
    RECENT_ROWS[0],
]


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append(url)
        return FakeResponse(self.payloads.pop(0))


def make_submissions(tmp_path, payloads):
    session = FakeSession(payloads)
    client = SecClient(
        user_agent="Personal Stock Research Assistant owner@example.org",
        cache_dir=tmp_path / "cache",
        session=session,
        sleep=lambda _: None,
    )
    return SecSubmissions(client), session


def root_payload(*, files=None, recent_rows=None):
    return {
        "cik": "0001045810",
        "name": "NVIDIA CORP",
        "filings": {
            "recent": columnar(recent_rows if recent_rows is not None else RECENT_ROWS),
            "files": files or [],
        },
    }


def test_current_filings_preserve_dates_forms_and_canonical_urls(tmp_path):
    submissions, session = make_submissions(tmp_path, [root_payload()])
    snapshot = submissions.fetch(
        IDENTITY,
        ticker="NVDA",
        since_date=date(2025, 1, 1),
    )
    assert len(snapshot.filings) == 2
    filing = next(value for value in snapshot.filings if value.form == "10-Q")
    assert filing.cik == "0001045810"
    assert filing.report_date == date(2026, 4, 26)
    assert filing.accepted_at == datetime(2026, 5, 20, 20, 6, 13, tzinfo=UTC)
    assert filing.availability_precision == "timestamp"
    assert filing.filing_index_url.endswith(
        "/000104581026000052/0001045810-26-000052-index.html"
    )
    assert filing.primary_document_url.endswith(
        "/000104581026000052/nvda-20260426.htm"
    )
    assert session.calls == [ROOT_URL]


def test_effective_selection_prefers_later_amendment_for_same_period(tmp_path):
    submissions, _ = make_submissions(tmp_path, [root_payload()])
    snapshot = submissions.fetch(
        IDENTITY,
        ticker="NVDA",
        since_date=date(2025, 1, 1),
    )
    effective = submissions.effective_filings(snapshot.filings)
    assert len(effective) == 1
    assert effective[0].form == "10-Q/A"
    assert effective[0].is_amendment is True

    before_amendment = submissions.effective_filings(
        snapshot.filings,
        available_at=datetime(2026, 5, 31, 23, 59, tzinfo=UTC),
    )
    assert len(before_amendment) == 1
    assert before_amendment[0].form == "10-Q"


def test_intersecting_history_file_is_loaded_and_deduplicated(tmp_path):
    files = [
        {
            "name": "CIK0001045810-submissions-001.json",
            "filingCount": 2,
            "filingFrom": "2025-01-01",
            "filingTo": "2026-05-20",
        }
    ]
    submissions, session = make_submissions(
        tmp_path,
        [root_payload(files=files), columnar(HISTORY_ROWS)],
    )
    snapshot = submissions.fetch(
        IDENTITY,
        ticker="NVDA",
        since_date=date(2025, 1, 1),
    )
    assert len(snapshot.filings) == 3
    assert {filing.base_form for filing in snapshot.filings} == {"10-K", "10-Q"}
    assert session.calls == [ROOT_URL, HISTORY_URL]
    annual = next(filing for filing in snapshot.filings if filing.base_form == "10-K")
    assert annual.accepted_at == datetime(2025, 2, 26, 21, 15, tzinfo=UTC)


def test_nonintersecting_history_file_is_not_requested(tmp_path):
    files = [
        {
            "name": "CIK0001045810-submissions-001.json",
            "filingCount": 1,
            "filingFrom": "2010-01-01",
            "filingTo": "2010-12-31",
        }
    ]
    submissions, session = make_submissions(tmp_path, [root_payload(files=files)])
    submissions.fetch(IDENTITY, ticker="NVDA", since_date=date(2025, 1, 1))
    assert session.calls == [ROOT_URL]


def test_missing_acceptance_timestamp_uses_date_precision(tmp_path):
    row = dict(RECENT_ROWS[0])
    row["acceptanceDateTime"] = ""
    submissions, _ = make_submissions(
        tmp_path, [root_payload(recent_rows=[row])]
    )
    filing = submissions.fetch(
        IDENTITY, ticker="NVDA", since_date=date(2025, 1, 1)
    ).filings[0]
    assert filing.accepted_at is None
    assert filing.availability_date == filing.filing_date
    assert filing.availability_precision == "date"


def test_malformed_columns_and_unsafe_history_names_fail_loudly(tmp_path):
    malformed = root_payload()
    malformed["filings"]["recent"]["filingDate"] = []
    submissions, _ = make_submissions(tmp_path, [malformed])
    with pytest.raises(SecPayloadError, match="inconsistent lengths"):
        submissions.fetch(IDENTITY, ticker="NVDA", since_date=date(2025, 1, 1))

    unsafe = root_payload(
        files=[
            {
                "name": "../outside.json",
                "filingFrom": "2025-01-01",
                "filingTo": "2026-01-01",
            }
        ]
    )
    submissions, _ = make_submissions(tmp_path / "second", [unsafe])
    with pytest.raises(SecPayloadError, match="unsafe history file"):
        submissions.fetch(IDENTITY, ticker="NVDA", since_date=date(2025, 1, 1))
