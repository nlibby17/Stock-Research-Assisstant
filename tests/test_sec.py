from __future__ import annotations

import copy
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from stockrank.data.sec import (
    SecClient,
    SecConfigurationError,
    SecIdentityDirectory,
    SecPayloadError,
    SecRequestError,
    load_sec_concept_specs,
    load_sec_entity_overrides,
    normalize_sec_ticker,
    validate_sec_configuration,
    validate_sec_user_agent,
)

IDENTITY_PAYLOAD = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [1045810, "NVIDIA CORP", "NVDA", "Nasdaq"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-B", "NYSE"],
    ],
}


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_client(tmp_path, session, **overrides):
    values = {
        "user_agent": "Personal Stock Research Assistant owner@example.org",
        "cache_dir": tmp_path / "sec-cache",
        "session": session,
        "requests_per_second": 5,
        "backoff_seconds": 0,
        "sleep": lambda _: None,
    }
    values.update(overrides)
    return SecClient(**values)


def test_user_agent_requires_application_contact_and_rejects_placeholder():
    assert validate_sec_user_agent(
        "Personal Stock Research Assistant owner@example.org"
    ).startswith("Personal")
    with pytest.raises(SecConfigurationError):
        validate_sec_user_agent("")
    with pytest.raises(SecConfigurationError):
        validate_sec_user_agent("Personal Stock Research your-email@example.com")
    with pytest.raises(SecConfigurationError):
        validate_sec_user_agent("Personal Stock Research without-contact")


def test_client_restricts_requests_to_approved_sec_https_hosts(tmp_path):
    client = make_client(tmp_path, FakeSession([]))
    with pytest.raises(SecConfigurationError):
        client.get_json(
            "http://www.sec.gov/files/company_tickers.json",
            cache_key="identity",
            ttl_hours=1,
        )
    with pytest.raises(SecConfigurationError):
        client.get_json(
            "https://example.org/company_tickers.json",
            cache_key="identity",
            ttl_hours=1,
        )


def test_identity_directory_parses_cik_exchange_and_ticker_alias(tmp_path):
    session = FakeSession([FakeResponse(200, IDENTITY_PAYLOAD)])
    client = make_client(tmp_path, session)
    snapshot = SecIdentityDirectory(client).fetch()
    assert snapshot.cache_hit is False
    assert snapshot.identities[0].cik == "0001045810"
    assert snapshot.identities[0].exchange == "Nasdaq"
    assert SecIdentityDirectory.resolve("BRK.B", snapshot.identities).ticker == "BRK-B"
    assert normalize_sec_ticker(" brk.b ") == "BRK-B"
    assert session.calls[0]["headers"]["User-Agent"].endswith("@example.org")


def test_fresh_cache_avoids_second_network_request(tmp_path):
    session = FakeSession([FakeResponse(200, IDENTITY_PAYLOAD)])
    client = make_client(tmp_path, session)
    directory = SecIdentityDirectory(client)
    first = directory.fetch()
    second = directory.fetch()
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(session.calls) == 1
    cache_file = next((tmp_path / "sec-cache").glob("*.json"))
    assert cache_file.read_bytes().startswith(b"\x1f\x8b")


def test_retryable_status_recovers_without_caching_failure(tmp_path):
    session = FakeSession(
        [
            FakeResponse(429, {"message": "slow down"}, "slow down"),
            FakeResponse(200, IDENTITY_PAYLOAD),
        ]
    )
    client = make_client(tmp_path, session, retries=1)
    snapshot = SecIdentityDirectory(client).fetch()
    assert len(snapshot.identities) == 2
    assert len(session.calls) == 2


def test_rate_limiter_spaces_live_request_starts(tmp_path):
    clock = [0.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    session = FakeSession(
        [FakeResponse(200, IDENTITY_PAYLOAD), FakeResponse(200, IDENTITY_PAYLOAD)]
    )
    client = make_client(
        tmp_path,
        session,
        requests_per_second=5,
        monotonic=lambda: clock[0],
        sleep=sleep,
    )
    client.get_json(
        "https://www.sec.gov/files/company_tickers_exchange.json",
        cache_key="identity",
        ttl_hours=1,
        force=True,
    )
    client.get_json(
        "https://www.sec.gov/files/company_tickers_exchange.json",
        cache_key="identity",
        ttl_hours=1,
        force=True,
    )
    assert waits == [0.2]


def test_stale_cache_fallback_is_explicit(tmp_path):
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    first_session = FakeSession([FakeResponse(200, IDENTITY_PAYLOAD)])
    client = make_client(tmp_path, first_session, now=lambda: clock[0])
    directory = SecIdentityDirectory(client, cache_ttl_hours=1)
    directory.fetch()

    clock[0] += timedelta(hours=2)
    failing_session = FakeSession([requests.ConnectionError("offline")])
    fallback_client = make_client(
        tmp_path,
        failing_session,
        now=lambda: clock[0],
        retries=0,
        allow_stale_on_error=True,
    )
    fallback = SecIdentityDirectory(fallback_client, cache_ttl_hours=1).fetch()
    assert fallback.cache_hit is True
    assert fallback.stale is True
    assert len(fallback.identities) == 2


def test_cache_older_than_maximum_staleness_is_rejected(tmp_path):
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    client = make_client(
        tmp_path,
        FakeSession([FakeResponse(200, IDENTITY_PAYLOAD)]),
        now=lambda: clock[0],
    )
    SecIdentityDirectory(client, cache_ttl_hours=1).fetch()
    clock[0] += timedelta(days=8)
    failing = make_client(
        tmp_path,
        FakeSession([requests.ConnectionError("offline")]),
        now=lambda: clock[0],
        retries=0,
        maximum_stale_hours=168,
    )
    with pytest.raises(SecRequestError, match="SEC request failed"):
        SecIdentityDirectory(failing, cache_ttl_hours=1).fetch()


def test_malformed_identity_payload_fails_loudly(tmp_path):
    session = FakeSession([FakeResponse(200, {"fields": ["cik"], "data": []})])
    client = make_client(tmp_path, session)
    with pytest.raises(SecPayloadError):
        SecIdentityDirectory(client).fetch()


def test_audited_entity_override_loads_padded_predecessor_cik(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "overrides.toml").write_text(
        """
[tickers.XOM]
additional_ciks = ["34088"]
reason = "Documented predecessor."
evidence_url = "https://www.sec.gov/Archives/edgar/data/34088/example-index.htm"
""".strip(),
        encoding="utf-8",
    )
    settings = SimpleNamespace(
        root=tmp_path,
        raw={"sec": {"entity_overrides_path": "config/overrides.toml"}},
    )
    assert load_sec_entity_overrides(settings) == {"XOM": ("0000034088",)}


def test_entity_override_rejects_non_sec_evidence(tmp_path):
    (tmp_path / "overrides.toml").write_text(
        """
[tickers.XOM]
additional_ciks = ["34088"]
reason = "Unverified source."
evidence_url = "https://example.org/not-sec"
""".strip(),
        encoding="utf-8",
    )
    settings = SimpleNamespace(
        root=tmp_path,
        raw={"sec": {"entity_overrides_path": "overrides.toml"}},
    )
    with pytest.raises(SecConfigurationError, match="official SEC evidence"):
        load_sec_entity_overrides(settings)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("identity_url", "http://www.sec.gov/files/test.json", "identity_url"),
        ("requests_per_second", 0, "requests_per_second"),
        ("requests_per_second", 11, "requests_per_second"),
        ("requests_per_second", float("nan"), "requests_per_second"),
        ("request_timeout_seconds", 0, "request_timeout_seconds"),
        ("request_retries", -1, "request_retries"),
        ("retry_backoff_seconds", -1, "retry_backoff_seconds"),
        ("identity_cache_ttl_hours", 0, "identity_cache_ttl_hours"),
        ("submissions_cache_ttl_hours", 0, "submissions_cache_ttl_hours"),
        ("filing_history_years", 0, "filing_history_years"),
        ("filing_forms", [], "filing_forms"),
        ("companyfacts_cache_ttl_hours", 0, "companyfacts_cache_ttl_hours"),
        ("companyfacts_full_refresh_hours", 0, "companyfacts_full_refresh_hours"),
        (
            "companyfacts_recent_filing_window_hours",
            -1,
            "companyfacts_recent_filing_window_hours",
        ),
        (
            "companyfacts_recent_filing_retry_hours",
            0,
            "companyfacts_recent_filing_retry_hours",
        ),
        ("companyfacts_history_years", 0, "companyfacts_history_years"),
        ("companyfacts_core_concepts", [], "companyfacts_core_concepts"),
        ("allow_stale_cache_on_error", "yes", "allow_stale_cache_on_error"),
        ("entity_overrides_path", "", "entity_overrides_path"),
        ("companyfacts_concepts_path", "", "companyfacts_concepts_path"),
        ("maximum_stale_cache_hours", 0, "maximum_stale_cache_hours"),
    ],
)
def test_local_sec_configuration_rejects_invalid_values(tmp_path, name, value, message):
    with (Path.cwd() / "config" / "preferences.toml").open("rb") as handle:
        raw = tomllib.load(handle)
    raw = copy.deepcopy(raw)
    raw["sec"][name] = value
    settings = SimpleNamespace(
        root=Path.cwd(),
        raw=raw,
        sec_user_agent="Stock Research Test test@example.org",
        sec_cache_dir=tmp_path,
    )

    errors = validate_sec_configuration(settings)

    assert any(message in error for error in errors)


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("[tickers.XOM\n", "could not be parsed"),
        (None, "could not be read"),
    ],
)
def test_entity_override_wraps_file_and_toml_errors(tmp_path, contents, message):
    path = tmp_path / "overrides.toml"
    if contents is None:
        path.mkdir()
    else:
        path.write_text(contents, encoding="utf-8")
    settings = SimpleNamespace(
        root=tmp_path,
        raw={"sec": {"entity_overrides_path": "overrides.toml"}},
    )

    with pytest.raises(SecConfigurationError, match=message):
        load_sec_entity_overrides(settings)


@pytest.mark.parametrize(
    ("contents", "message"),
    [("[concepts.revenue\n", "could not be parsed"), (None, "could not be read")],
)
def test_companyfacts_concept_map_wraps_file_and_toml_errors(tmp_path, contents, message):
    path = tmp_path / "concepts.toml"
    if contents is None:
        path.mkdir()
    else:
        path.write_text(contents, encoding="utf-8")
    settings = SimpleNamespace(
        root=tmp_path,
        raw={"sec": {"companyfacts_concepts_path": "concepts.toml"}},
    )

    with pytest.raises(SecConfigurationError, match=message):
        load_sec_concept_specs(settings)


def test_local_sec_configuration_rejects_missing_override_file(tmp_path):
    with (Path.cwd() / "config" / "preferences.toml").open("rb") as handle:
        raw = tomllib.load(handle)
    raw = copy.deepcopy(raw)
    raw["sec"]["entity_overrides_path"] = "config/missing-overrides.toml"
    settings = SimpleNamespace(
        root=Path.cwd(),
        raw=raw,
        sec_user_agent="Stock Research Test test@example.org",
        sec_cache_dir=tmp_path,
    )

    errors = validate_sec_configuration(settings)

    assert any("entity overrides file not found" in error for error in errors)


def test_companyfacts_concept_map_preserves_explicit_member_priority(tmp_path):
    (tmp_path / "concepts.toml").write_text(
        """
[concepts.revenue]
period_type = "duration"
units = ["USD"]
members = ["us-gaap:PreferredRevenue", "us-gaap:Revenues"]
""".strip(),
        encoding="utf-8",
    )
    settings = SimpleNamespace(
        root=tmp_path,
        raw={"sec": {"companyfacts_concepts_path": "concepts.toml"}},
    )
    specs = load_sec_concept_specs(settings)
    assert specs[0].canonical_name == "revenue"
    assert specs[0].members == (
        ("us-gaap", "PreferredRevenue"),
        ("us-gaap", "Revenues"),
    )


def test_companyfacts_concept_map_rejects_implicit_or_invalid_members(tmp_path):
    (tmp_path / "concepts.toml").write_text(
        """
[concepts.revenue]
period_type = "duration"
units = ["USD"]
members = ["unqualified-concept"]
""".strip(),
        encoding="utf-8",
    )
    settings = SimpleNamespace(
        root=tmp_path,
        raw={"sec": {"companyfacts_concepts_path": "concepts.toml"}},
    )
    with pytest.raises(SecConfigurationError, match="invalid member"):
        load_sec_concept_specs(settings)
