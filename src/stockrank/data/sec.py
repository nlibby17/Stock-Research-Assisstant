from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import requests

from stockrank.models import SecCompanyFact, SecFiling

if TYPE_CHECKING:
    from stockrank.config import Settings

SEC_IDENTITY_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_ALLOWED_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
SEC_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
SEC_CACHE_SCHEMA_VERSION = 1
SEC_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)
EMAIL_PATTERN = re.compile(r"(?<!\S)[^@\s]+@[^@\s]+\.[^@\s]+(?!\S)")
ACCESSION_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")
SUBMISSION_FILE_PATTERN = re.compile(r"^CIK\d{10}-submissions-\d{3}\.json$")
SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
SEC_COMPANYFACTS_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"
XBRL_MEMBER_PATTERN = re.compile(
    r"^(?P<taxonomy>[a-z][a-z0-9-]*):(?P<concept>[A-Za-z_][A-Za-z0-9_.-]*)$"
)


class SecError(RuntimeError):
    """Base class for SEC provider failures."""


class SecConfigurationError(SecError):
    """Raised when the SEC client is configured unsafely."""


class SecRequestError(SecError):
    """Raised when an SEC request cannot be completed."""


class SecPayloadError(SecError):
    """Raised when an SEC response does not match the documented JSON shape."""


@dataclass(frozen=True)
class SecJsonDocument:
    payload: Any
    source_url: str
    fetched_at: datetime
    cache_hit: bool
    stale: bool = False


@dataclass(frozen=True)
class SecCompanyIdentity:
    cik: str
    name: str
    ticker: str
    exchange: str


@dataclass(frozen=True)
class SecIdentitySnapshot:
    identities: tuple[SecCompanyIdentity, ...]
    source_url: str
    fetched_at: datetime
    cache_hit: bool
    stale: bool


@dataclass(frozen=True)
class SecSubmissionSnapshot:
    cik: str
    ticker: str
    company_name: str
    filings: tuple[SecFiling, ...]
    source_urls: tuple[str, ...]
    fetched_at: datetime
    cache_hits: int
    documents_checked: int
    stale: bool


@dataclass(frozen=True)
class SecConceptSpec:
    canonical_name: str
    period_type: str
    units: tuple[str, ...]
    members: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SecCompanyFactsSnapshot:
    cik: str
    ticker: str
    company_name: str
    facts: tuple[SecCompanyFact, ...]
    source_url: str
    fetched_at: datetime
    cache_hit: bool
    stale: bool
    configured_concepts: tuple[str, ...]
    present_concepts: tuple[str, ...]
    unmatched_accessions: int


def validate_sec_user_agent(value: str) -> str:
    normalized = " ".join(value.split())
    lowered = normalized.lower()
    if not normalized:
        raise SecConfigurationError(
            "SEC_USER_AGENT is missing. Add an application name and contact email to .env."
        )
    if "your-email" in lowered or "example.com" in lowered:
        raise SecConfigurationError(
            "SEC_USER_AGENT still contains a placeholder; configure a real contact email."
        )
    if not EMAIL_PATTERN.search(normalized):
        raise SecConfigurationError(
            "SEC_USER_AGENT must contain an application name and contact email."
        )
    if len(normalized) < 12:
        raise SecConfigurationError("SEC_USER_AGENT is too short to identify the application.")
    return normalized


def normalize_sec_ticker(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


def validate_sec_configuration(settings: Settings) -> list[str]:
    """Validate all local SEC settings without provider or network access."""
    errors: list[str] = []
    config = settings.raw.get("sec", {})
    if not isinstance(config, dict):
        return ["sec must be a configuration table"]

    try:
        validate_sec_user_agent(settings.sec_user_agent)
    except SecConfigurationError as exc:
        errors.append(str(exc))

    identity_url = str(config.get("identity_url", "")).strip()
    parsed_identity_url = urlparse(identity_url)
    if (
        parsed_identity_url.scheme != "https"
        or parsed_identity_url.hostname not in SEC_ALLOWED_HOSTS
    ):
        errors.append("sec.identity_url must use HTTPS on an approved sec.gov host")

    def numeric(
        name: str, *, allow_zero: bool = False, maximum: float | None = None
    ) -> None:
        try:
            value = float(config[name])
        except (KeyError, TypeError, ValueError):
            errors.append(f"sec.{name} must be a valid number")
            return
        invalid_minimum = value < 0 if allow_zero else value <= 0
        if not math.isfinite(value) or invalid_minimum or (
            maximum is not None and value > maximum
        ):
            requirement = "nonnegative" if allow_zero else "positive"
            if maximum is not None:
                requirement += f" and no more than {maximum:g}"
            errors.append(f"sec.{name} must be {requirement}")

    def integer(name: str, *, minimum: int) -> None:
        value = config.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            errors.append(f"sec.{name} must be an integer of at least {minimum}")

    numeric("requests_per_second", maximum=10)
    numeric("request_timeout_seconds")
    integer("request_retries", minimum=0)
    numeric("retry_backoff_seconds", allow_zero=True)
    numeric("identity_cache_ttl_hours")
    numeric("submissions_cache_ttl_hours")
    integer("filing_history_years", minimum=1)
    numeric("companyfacts_cache_ttl_hours")
    numeric("companyfacts_full_refresh_hours")
    numeric("companyfacts_recent_filing_window_hours", allow_zero=True)
    numeric("companyfacts_recent_filing_retry_hours")
    integer("companyfacts_history_years", minimum=1)
    numeric("maximum_stale_cache_hours")

    for name in ("filing_forms", "companyfacts_core_concepts"):
        values = config.get(name)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            errors.append(f"sec.{name} must be a nonempty array of nonempty strings")

    if not isinstance(config.get("allow_stale_cache_on_error"), bool):
        errors.append("sec.allow_stale_cache_on_error must be true or false")
    for name in ("entity_overrides_path", "companyfacts_concepts_path"):
        if not str(config.get(name, "")).strip():
            errors.append(f"sec.{name} must not be empty")

    overrides_path = Path(str(config.get("entity_overrides_path", "")))
    if not overrides_path.is_absolute():
        overrides_path = settings.root / overrides_path
    if not overrides_path.is_file():
        errors.append(f"SEC entity overrides file not found: {overrides_path}")
    else:
        try:
            load_sec_entity_overrides(settings)
        except SecConfigurationError as exc:
            errors.append(str(exc))
    try:
        load_sec_concept_specs(settings)
    except SecConfigurationError as exc:
        errors.append(str(exc))
    return errors


def load_sec_entity_overrides(settings: Settings) -> dict[str, tuple[str, ...]]:
    configured_path = settings.raw.get("sec", {}).get(
        "entity_overrides_path", "config/sec_entity_overrides.toml"
    )
    path = Path(str(configured_path))
    if not path.is_absolute():
        path = settings.root / path
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise SecConfigurationError(
            f"SEC entity overrides could not be parsed: {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise SecConfigurationError(f"SEC entity overrides could not be read: {path}: {exc}") from exc
    ticker_records = payload.get("tickers", {})
    if not isinstance(ticker_records, dict):
        raise SecConfigurationError("SEC entity overrides must contain a tickers table.")
    output: dict[str, tuple[str, ...]] = {}
    for ticker, record in ticker_records.items():
        if not isinstance(record, dict):
            raise SecConfigurationError(f"SEC entity override for {ticker} must be a table.")
        values = record.get("additional_ciks", [])
        if not isinstance(values, list):
            raise SecConfigurationError(
                f"SEC entity override additional_ciks for {ticker} must be an array."
            )
        reason = str(record.get("reason", "")).strip()
        evidence_url = str(record.get("evidence_url", "")).strip()
        evidence = urlparse(evidence_url)
        if not reason:
            raise SecConfigurationError(f"SEC entity override for {ticker} requires a reason.")
        if evidence.scheme != "https" or evidence.hostname not in SEC_ALLOWED_HOSTS:
            raise SecConfigurationError(
                f"SEC entity override for {ticker} requires an official SEC evidence URL."
            )
        ciks: list[str] = []
        for raw_cik in values:
            cik = str(raw_cik).strip()
            if not cik.isdigit() or len(cik) > 10:
                raise SecConfigurationError(
                    f"SEC entity override for {ticker} contains invalid CIK: {cik}"
                )
            ciks.append(cik.zfill(10))
        output[normalize_sec_ticker(str(ticker))] = tuple(dict.fromkeys(ciks))
    return output


def load_sec_concept_specs(settings: Settings) -> tuple[SecConceptSpec, ...]:
    configured_path = settings.raw.get("sec", {}).get(
        "companyfacts_concepts_path", "config/sec_companyfacts.toml"
    )
    path = Path(str(configured_path))
    if not path.is_absolute():
        path = settings.root / path
    if not path.exists():
        raise SecConfigurationError(f"SEC Company Facts concept map not found: {path}")
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise SecConfigurationError(
            f"SEC Company Facts concept map could not be parsed: {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise SecConfigurationError(
            f"SEC Company Facts concept map could not be read: {path}: {exc}"
        ) from exc
    concepts = payload.get("concepts")
    if not isinstance(concepts, dict) or not concepts:
        raise SecConfigurationError("SEC Company Facts concept map must define concepts.")

    output: list[SecConceptSpec] = []
    for canonical_name, record in concepts.items():
        if not isinstance(record, dict):
            raise SecConfigurationError(
                f"SEC Company Facts concept {canonical_name} must be a table."
            )
        period_type = str(record.get("period_type", "")).strip().lower()
        if period_type not in {"instant", "duration"}:
            raise SecConfigurationError(
                f"SEC Company Facts concept {canonical_name} has invalid period_type."
            )
        units = record.get("units")
        members = record.get("members")
        if (
            not isinstance(units, list)
            or not units
            or not all(isinstance(unit, str) and unit.strip() for unit in units)
        ):
            raise SecConfigurationError(
                f"SEC Company Facts concept {canonical_name} requires units."
            )
        if not isinstance(members, list) or not members:
            raise SecConfigurationError(
                f"SEC Company Facts concept {canonical_name} requires members."
            )
        parsed_members: list[tuple[str, str]] = []
        for member in members:
            match = XBRL_MEMBER_PATTERN.fullmatch(str(member).strip())
            if not match:
                raise SecConfigurationError(
                    f"SEC Company Facts concept {canonical_name} has invalid member: {member}"
                )
            parsed_members.append((match["taxonomy"], match["concept"]))
        output.append(
            SecConceptSpec(
                canonical_name=str(canonical_name).strip(),
                period_type=period_type,
                units=tuple(dict.fromkeys(str(unit).strip() for unit in units)),
                members=tuple(dict.fromkeys(parsed_members)),
            )
        )
    return tuple(output)


class SecClient:
    """Small SEC JSON client with declared identity, throttling, retries, and disk cache."""

    def __init__(
        self,
        *,
        user_agent: str,
        cache_dir: Path,
        requests_per_second: float = 5.0,
        timeout_seconds: float = 20.0,
        retries: int = 2,
        backoff_seconds: float = 1.0,
        allow_stale_on_error: bool = True,
        maximum_stale_hours: float = 168.0,
        session: Any | None = None,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self.user_agent = validate_sec_user_agent(user_agent)
        if not 0 < requests_per_second <= 10:
            raise SecConfigurationError(
                "SEC requests_per_second must be greater than zero and no more than 10."
            )
        if timeout_seconds <= 0:
            raise SecConfigurationError("SEC request_timeout_seconds must be greater than zero.")
        if retries < 0:
            raise SecConfigurationError("SEC request_retries cannot be negative.")
        if backoff_seconds < 0:
            raise SecConfigurationError("SEC retry_backoff_seconds cannot be negative.")
        if maximum_stale_hours <= 0:
            raise SecConfigurationError("SEC maximum_stale_cache_hours must be positive.")
        self.cache_dir = cache_dir
        self.requests_per_second = float(requests_per_second)
        self.timeout_seconds = float(timeout_seconds)
        self.retries = int(retries)
        self.backoff_seconds = float(backoff_seconds)
        self.allow_stale_on_error = bool(allow_stale_on_error)
        self.maximum_stale_hours = float(maximum_stale_hours)
        self.session = session or requests.Session()
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._request_lock = threading.Lock()
        self._last_request_at: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings, **overrides: Any) -> SecClient:
        config = settings.raw.get("sec", {})
        values: dict[str, Any] = {
            "user_agent": settings.sec_user_agent,
            "cache_dir": settings.sec_cache_dir,
            "requests_per_second": float(config.get("requests_per_second", 5.0)),
            "timeout_seconds": float(config.get("request_timeout_seconds", 20.0)),
            "retries": int(config.get("request_retries", 2)),
            "backoff_seconds": float(config.get("retry_backoff_seconds", 1.0)),
            "allow_stale_on_error": bool(config.get("allow_stale_cache_on_error", True)),
            "maximum_stale_hours": float(config.get("maximum_stale_cache_hours", 168.0)),
        }
        values.update(overrides)
        return cls(**values)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }

    def get_json(
        self,
        url: str,
        *,
        cache_key: str,
        ttl_hours: float,
        force: bool = False,
    ) -> SecJsonDocument:
        self._validate_url(url)
        cached = self._read_cache(url, cache_key)
        if cached and not force and self._is_fresh(cached.fetched_at, ttl_hours):
            return cached

        error: Exception | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(self.backoff_seconds * (2 ** (attempt - 1)))
            self._throttle()
            try:
                response = self.session.get(
                    url,
                    headers=self.headers,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                error = exc
                continue

            if response.status_code == 200:
                try:
                    payload = response.json()
                except (requests.JSONDecodeError, ValueError) as exc:
                    error = SecPayloadError(f"SEC returned invalid JSON for {url}: {exc}")
                    continue
                fetched_at = self._now()
                self._write_cache(url, cache_key, fetched_at, payload)
                return SecJsonDocument(
                    payload=payload,
                    source_url=url,
                    fetched_at=fetched_at,
                    cache_hit=False,
                )

            detail = self._safe_response_detail(response)
            error = SecRequestError(
                f"SEC request failed with HTTP {response.status_code} for {url}{detail}"
            )
            if response.status_code not in SEC_RETRYABLE_STATUS_CODES:
                break

        if (
            cached
            and self.allow_stale_on_error
            and self._now() - cached.fetched_at <= timedelta(hours=self.maximum_stale_hours)
        ):
            return SecJsonDocument(
                payload=cached.payload,
                source_url=cached.source_url,
                fetched_at=cached.fetched_at,
                cache_hit=True,
                stale=True,
            )
        raise SecRequestError(f"SEC request failed after {self.retries + 1} attempt(s): {error}")

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in SEC_ALLOWED_HOSTS:
            raise SecConfigurationError(
                "SEC requests must use HTTPS and an approved sec.gov data host."
            )

    def _throttle(self) -> None:
        minimum_interval = 1.0 / self.requests_per_second
        with self._request_lock:
            now = self._monotonic()
            if self._last_request_at is not None:
                wait_for = minimum_interval - (now - self._last_request_at)
                if wait_for > 0:
                    self._sleep(wait_for)
                    now = self._monotonic()
            self._last_request_at = now

    def _cache_path(self, url: str, cache_key: str) -> Path:
        safe_key = re.sub(r"[^a-zA-Z0-9_-]+", "-", cache_key).strip("-") or "sec"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{safe_key}-{digest}.json"

    def _read_cache(self, url: str, cache_key: str) -> SecJsonDocument | None:
        path = self._cache_path(url, cache_key)
        if not path.exists():
            return None
        try:
            content = path.read_bytes()
            if content.startswith(b"\x1f\x8b"):
                content = gzip.decompress(content)
            record = json.loads(content.decode("utf-8"))
            if not isinstance(record, dict):
                return None
            schema_version = record.get("schema_version")
            if not isinstance(schema_version, int) or isinstance(schema_version, bool):
                return None
            if schema_version != SEC_CACHE_SCHEMA_VERSION:
                return None
            if record.get("source_url") != url:
                return None
            fetched_at = datetime.fromisoformat(record["fetched_at"])
            if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
                return None
            fetched_at = fetched_at.astimezone(UTC)
            now = self._now()
            if now.tzinfo is None or now.utcoffset() is None:
                return None
            if fetched_at > now.astimezone(UTC) + SEC_CLOCK_SKEW_TOLERANCE:
                return None
            return SecJsonDocument(
                payload=record["payload"],
                source_url=url,
                fetched_at=fetched_at,
                cache_hit=True,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write_cache(self, url: str, cache_key: str, fetched_at: datetime, payload: Any) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(url, cache_key)
        temp_path = path.with_suffix(".tmp")
        record = {
            "schema_version": SEC_CACHE_SCHEMA_VERSION,
            "source_url": url,
            "fetched_at": fetched_at.isoformat(),
            "payload": payload,
        }
        content = json.dumps(record, separators=(",", ":")).encode("utf-8")
        temp_path.write_bytes(gzip.compress(content, compresslevel=6))
        temp_path.replace(path)

    def _is_fresh(self, fetched_at: datetime, ttl_hours: float) -> bool:
        return fetched_at + timedelta(hours=ttl_hours) > self._now()

    @staticmethod
    def _safe_response_detail(response: Any) -> str:
        text = str(getattr(response, "text", "")).strip().replace("\n", " ")
        return f": {text[:200]}" if text else ""


class SecIdentityDirectory:
    def __init__(
        self,
        client: SecClient,
        *,
        url: str = SEC_IDENTITY_URL,
        cache_ttl_hours: float = 24.0,
    ):
        self.client = client
        self.url = url
        if cache_ttl_hours <= 0:
            raise SecConfigurationError("SEC identity_cache_ttl_hours must be positive.")
        self.cache_ttl_hours = cache_ttl_hours

    @classmethod
    def from_settings(
        cls, settings: Settings, client: SecClient | None = None
    ) -> SecIdentityDirectory:
        config = settings.raw.get("sec", {})
        return cls(
            client or SecClient.from_settings(settings),
            url=str(config.get("identity_url", SEC_IDENTITY_URL)),
            cache_ttl_hours=float(config.get("identity_cache_ttl_hours", 24.0)),
        )

    def fetch(self, *, force: bool = False) -> SecIdentitySnapshot:
        document = self.client.get_json(
            self.url,
            cache_key="company-tickers-exchange",
            ttl_hours=self.cache_ttl_hours,
            force=force,
        )
        identities = self._parse(document.payload)
        return SecIdentitySnapshot(
            identities=identities,
            source_url=document.source_url,
            fetched_at=document.fetched_at,
            cache_hit=document.cache_hit,
            stale=document.stale,
        )

    @staticmethod
    def _parse(payload: Any) -> tuple[SecCompanyIdentity, ...]:
        if not isinstance(payload, dict):
            raise SecPayloadError("SEC identity payload must be a JSON object.")
        fields = payload.get("fields")
        rows = payload.get("data")
        required = ("cik", "name", "ticker", "exchange")
        if not isinstance(fields, list) or not isinstance(rows, list):
            raise SecPayloadError("SEC identity payload is missing fields or data arrays.")
        try:
            positions = {field: fields.index(field) for field in required}
        except ValueError as exc:
            raise SecPayloadError(f"SEC identity payload is missing required field: {exc}") from exc

        identities: list[SecCompanyIdentity] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < len(fields):
                raise SecPayloadError("SEC identity payload contains a malformed row.")
            cik_value = str(row[positions["cik"]]).strip()
            ticker = normalize_sec_ticker(str(row[positions["ticker"]]))
            if not cik_value.isdigit() or len(cik_value) > 10 or not ticker:
                raise SecPayloadError("SEC identity payload contains an invalid CIK or ticker.")
            identities.append(
                SecCompanyIdentity(
                    cik=cik_value.zfill(10),
                    name=str(row[positions["name"]]).strip(),
                    ticker=ticker,
                    exchange=str(row[positions["exchange"]]).strip(),
                )
            )
        if not identities:
            raise SecPayloadError("SEC identity payload contains no identities.")
        return tuple(identities)

    @staticmethod
    def index_by_ticker(
        identities: tuple[SecCompanyIdentity, ...],
    ) -> dict[str, SecCompanyIdentity]:
        return {identity.ticker: identity for identity in identities}

    @classmethod
    def resolve(
        cls, ticker: str, identities: tuple[SecCompanyIdentity, ...]
    ) -> SecCompanyIdentity | None:
        return cls.index_by_ticker(identities).get(normalize_sec_ticker(ticker))


def _parse_date(value: Any, *, field: str, required: bool) -> date | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise SecPayloadError(f"SEC filing is missing required {field}.")
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise SecPayloadError(f"SEC filing contains invalid {field}: {text}") from exc


def _parse_acceptance_datetime(value: Any) -> tuple[str | None, datetime | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, None
    # SEC defines the acceptance clock as Eastern time. The submissions feed
    # commonly appends "Z" to that wall-clock value, so preserve the raw string
    # but localize the clock to America/New_York before converting to true UTC.
    normalized = raw.removesuffix("Z")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SecPayloadError(f"SEC filing contains invalid acceptanceDateTime: {raw}") from exc
    if raw.endswith("Z") or parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    return raw, parsed.astimezone(UTC)


def _filing_urls(
    cik: str, accession_number: str, primary_document: str | None
) -> tuple[str, str | None]:
    accession_compact = accession_number.replace("-", "")
    archive_cik = str(int(cik))
    directory = f"https://www.sec.gov/Archives/edgar/data/{archive_cik}/{accession_compact}"
    index_url = f"{directory}/{accession_number}-index.html"
    if not primary_document:
        return index_url, None
    if Path(primary_document).name != primary_document or ".." in primary_document:
        raise SecPayloadError("SEC filing contains an unsafe primaryDocument path.")
    return index_url, f"{directory}/{quote(primary_document)}"


class SecSubmissions:
    REQUIRED_COLUMNS = ("accessionNumber", "filingDate", "form")

    def __init__(
        self,
        client: SecClient,
        *,
        cache_ttl_hours: float = 6.0,
        forms: tuple[str, ...] = ("10-K", "10-K/A", "10-Q", "10-Q/A"),
    ):
        if cache_ttl_hours <= 0:
            raise SecConfigurationError("SEC submissions_cache_ttl_hours must be positive.")
        normalized_forms = tuple(dict.fromkeys(form.strip().upper() for form in forms if form))
        if not normalized_forms:
            raise SecConfigurationError("SEC filing_forms cannot be empty.")
        self.client = client
        self.cache_ttl_hours = cache_ttl_hours
        self.forms = normalized_forms

    @classmethod
    def from_settings(cls, settings: Settings, client: SecClient | None = None) -> SecSubmissions:
        config = settings.raw.get("sec", {})
        return cls(
            client or SecClient.from_settings(settings),
            cache_ttl_hours=float(config.get("submissions_cache_ttl_hours", 6.0)),
            forms=tuple(
                str(form)
                for form in config.get("filing_forms", ("10-K", "10-K/A", "10-Q", "10-Q/A"))
            ),
        )

    def fetch(
        self,
        identity: SecCompanyIdentity,
        *,
        ticker: str,
        since_date: date,
        force: bool = False,
    ) -> SecSubmissionSnapshot:
        root_url = f"{SEC_SUBMISSIONS_BASE_URL}/CIK{identity.cik}.json"
        root_document = self.client.get_json(
            root_url,
            cache_key=f"submissions-{identity.cik}",
            ttl_hours=self.cache_ttl_hours,
            force=force,
        )
        if not isinstance(root_document.payload, dict):
            raise SecPayloadError("SEC submissions payload must be a JSON object.")
        payload_cik = str(root_document.payload.get("cik", "")).strip()
        if not payload_cik.isdigit() or payload_cik.zfill(10) != identity.cik:
            raise SecPayloadError("SEC submissions payload CIK does not match requested identity.")
        company_name = str(root_document.payload.get("name") or identity.name).strip()
        filings_node = root_document.payload.get("filings")
        if not isinstance(filings_node, dict):
            raise SecPayloadError("SEC submissions payload is missing the filings object.")
        recent = filings_node.get("recent")
        if not isinstance(recent, dict):
            raise SecPayloadError("SEC submissions payload is missing filings.recent.")

        filings_by_accession = {
            filing.accession_number: filing
            for filing in self._parse_columnar(
                recent,
                identity=identity,
                ticker=ticker,
                company_name=company_name,
                source_url=root_url,
                fetched_at=root_document.fetched_at,
                since_date=since_date,
            )
        }
        documents = [root_document]
        files = filings_node.get("files", [])
        if files is None:
            files = []
        if not isinstance(files, list):
            raise SecPayloadError("SEC submissions filings.files must be an array.")
        for file_record in files:
            if not self._history_file_intersects(file_record, since_date):
                continue
            file_name = str(file_record.get("name", "")).strip()
            if not SUBMISSION_FILE_PATTERN.fullmatch(file_name):
                raise SecPayloadError(f"SEC submissions contains unsafe history file: {file_name}")
            history_url = f"{SEC_SUBMISSIONS_BASE_URL}/{file_name}"
            history_document = self.client.get_json(
                history_url,
                cache_key=f"submissions-history-{file_name.removesuffix('.json')}",
                ttl_hours=self.cache_ttl_hours,
                force=force,
            )
            if not isinstance(history_document.payload, dict):
                raise SecPayloadError("SEC historical submissions payload must be an object.")
            history_node = history_document.payload
            if isinstance(history_node.get("filings"), dict):
                history_node = history_node["filings"].get("recent", history_node)
            for filing in self._parse_columnar(
                history_node,
                identity=identity,
                ticker=ticker,
                company_name=company_name,
                source_url=history_url,
                fetched_at=history_document.fetched_at,
                since_date=since_date,
            ):
                filings_by_accession.setdefault(filing.accession_number, filing)
            documents.append(history_document)

        filings = tuple(
            sorted(
                filings_by_accession.values(),
                key=lambda value: (
                    value.accepted_at
                    or datetime.combine(value.filing_date, datetime_time.min, tzinfo=UTC),
                    value.accession_number,
                ),
                reverse=True,
            )
        )
        return SecSubmissionSnapshot(
            cik=identity.cik,
            ticker=normalize_sec_ticker(ticker),
            company_name=company_name,
            filings=filings,
            source_urls=tuple(document.source_url for document in documents),
            fetched_at=max(document.fetched_at for document in documents),
            cache_hits=sum(document.cache_hit for document in documents),
            documents_checked=len(documents),
            stale=any(document.stale for document in documents),
        )

    def _parse_columnar(
        self,
        payload: dict[str, Any],
        *,
        identity: SecCompanyIdentity,
        ticker: str,
        company_name: str,
        source_url: str,
        fetched_at: datetime,
        since_date: date,
    ) -> tuple[SecFiling, ...]:
        for column in self.REQUIRED_COLUMNS:
            if not isinstance(payload.get(column), list):
                raise SecPayloadError(f"SEC submissions payload is missing {column} array.")
        row_count = len(payload["accessionNumber"])
        if any(len(payload[column]) != row_count for column in self.REQUIRED_COLUMNS):
            raise SecPayloadError("SEC submissions required columns have inconsistent lengths.")

        filings: list[SecFiling] = []
        for index in range(row_count):
            form = self._column_value(payload, "form", index).upper()
            if form not in self.forms:
                continue
            filing_date = _parse_date(
                self._column_value(payload, "filingDate", index),
                field="filingDate",
                required=True,
            )
            assert filing_date is not None
            if filing_date < since_date:
                continue
            accession_number = self._column_value(payload, "accessionNumber", index)
            if not ACCESSION_PATTERN.fullmatch(accession_number):
                raise SecPayloadError(
                    f"SEC filing contains invalid accessionNumber: {accession_number}"
                )
            report_date = _parse_date(
                self._column_value(payload, "reportDate", index),
                field="reportDate",
                required=False,
            )
            acceptance_raw, accepted_at = _parse_acceptance_datetime(
                self._column_value(payload, "acceptanceDateTime", index)
            )
            primary_document = self._column_value(payload, "primaryDocument", index) or None
            filing_index_url, primary_document_url = _filing_urls(
                identity.cik, accession_number, primary_document
            )
            filings.append(
                SecFiling(
                    cik=identity.cik,
                    ticker=normalize_sec_ticker(ticker),
                    company_name=company_name,
                    accession_number=accession_number,
                    form=form,
                    base_form=form.removesuffix("/A"),
                    is_amendment=form.endswith("/A"),
                    filing_date=filing_date,
                    report_date=report_date,
                    acceptance_datetime=acceptance_raw,
                    accepted_at=accepted_at,
                    availability_date=accepted_at.date() if accepted_at else filing_date,
                    availability_precision="timestamp" if accepted_at else "date",
                    primary_document=primary_document,
                    filing_index_url=filing_index_url,
                    primary_document_url=primary_document_url,
                    source_url=source_url,
                    fetched_at=fetched_at,
                )
            )
        return tuple(filings)

    @staticmethod
    def _column_value(payload: dict[str, Any], column: str, index: int) -> str:
        values = payload.get(column)
        if not isinstance(values, list) or index >= len(values) or values[index] is None:
            return ""
        return str(values[index]).strip()

    @staticmethod
    def _history_file_intersects(file_record: Any, since_date: date) -> bool:
        if not isinstance(file_record, dict):
            raise SecPayloadError("SEC submissions contains a malformed history file record.")
        filing_to = _parse_date(
            file_record.get("filingTo"), field="filings.files.filingTo", required=False
        )
        return filing_to is None or filing_to >= since_date

    @staticmethod
    def effective_filings(
        filings: tuple[SecFiling, ...], *, available_at: datetime | None = None
    ) -> tuple[SecFiling, ...]:
        if available_at is not None and available_at.tzinfo is None:
            raise ValueError("SEC filing available_at cutoff must include a timezone.")
        selected: dict[tuple[str, date], SecFiling] = {}
        for filing in filings:
            if available_at is not None:
                if filing.accepted_at and filing.accepted_at > available_at:
                    continue
                if not filing.accepted_at and filing.availability_date > available_at.date():
                    continue
            period = filing.report_date or filing.filing_date
            key = (filing.base_form, period)
            current = selected.get(key)
            filing_order = (
                filing.accepted_at
                or datetime.combine(filing.filing_date, datetime_time.min, tzinfo=UTC),
                filing.accession_number,
            )
            current_order = (
                (
                    (
                        current.accepted_at
                        or datetime.combine(current.filing_date, datetime_time.min, tzinfo=UTC)
                    ),
                    current.accession_number,
                )
                if current
                else None
            )
            if current_order is None or filing_order > current_order:
                selected[key] = filing
        return tuple(
            sorted(
                selected.values(),
                key=lambda value: (
                    value.accepted_at
                    or datetime.combine(value.filing_date, datetime_time.min, tzinfo=UTC),
                    value.accession_number,
                ),
                reverse=True,
            )
        )


class SecCompanyFacts:
    """Normalize an explicit allowlist of entity-wide SEC XBRL facts."""

    def __init__(
        self,
        client: SecClient,
        *,
        concept_specs: tuple[SecConceptSpec, ...],
        cache_ttl_hours: float = 6.0,
        forms: tuple[str, ...] = ("10-K", "10-K/A", "10-Q", "10-Q/A"),
    ):
        if cache_ttl_hours <= 0:
            raise SecConfigurationError("SEC companyfacts_cache_ttl_hours must be positive.")
        if not concept_specs:
            raise SecConfigurationError("SEC Company Facts requires a concept allowlist.")
        normalized_forms = tuple(dict.fromkeys(form.strip().upper() for form in forms if form))
        if not normalized_forms:
            raise SecConfigurationError("SEC filing_forms cannot be empty.")
        canonical_names = [spec.canonical_name for spec in concept_specs]
        if len(set(canonical_names)) != len(canonical_names):
            raise SecConfigurationError("SEC Company Facts canonical names must be unique.")
        self.client = client
        self.concept_specs = concept_specs
        self.cache_ttl_hours = cache_ttl_hours
        self.forms = normalized_forms

    @classmethod
    def from_settings(cls, settings: Settings, client: SecClient | None = None) -> SecCompanyFacts:
        config = settings.raw.get("sec", {})
        return cls(
            client or SecClient.from_settings(settings),
            concept_specs=load_sec_concept_specs(settings),
            cache_ttl_hours=float(config.get("companyfacts_cache_ttl_hours", 6.0)),
            forms=tuple(
                str(form)
                for form in config.get("filing_forms", ("10-K", "10-K/A", "10-Q", "10-Q/A"))
            ),
        )

    def fetch(
        self,
        identity: SecCompanyIdentity,
        *,
        ticker: str,
        since_date: date,
        filings: tuple[SecFiling, ...] = (),
        force: bool = False,
    ) -> SecCompanyFactsSnapshot:
        url = f"{SEC_COMPANYFACTS_BASE_URL}/CIK{identity.cik}.json"
        document = self.client.get_json(
            url,
            cache_key=f"companyfacts-{identity.cik}",
            ttl_hours=self.cache_ttl_hours,
            force=force,
        )
        payload = document.payload
        if not isinstance(payload, dict):
            raise SecPayloadError("SEC Company Facts payload must be a JSON object.")
        payload_cik = str(payload.get("cik", "")).strip()
        if not payload_cik.isdigit() or payload_cik.zfill(10) != identity.cik:
            raise SecPayloadError("SEC Company Facts payload CIK does not match the request.")
        facts_node = payload.get("facts")
        if not isinstance(facts_node, dict):
            raise SecPayloadError("SEC Company Facts payload is missing facts.")
        company_name = str(payload.get("entityName") or identity.name).strip()
        filing_index = {
            filing.accession_number: filing for filing in filings if filing.cik == identity.cik
        }
        normalized: dict[tuple[Any, ...], SecCompanyFact] = {}
        unmatched_accessions: set[str] = set()

        for spec in self.concept_specs:
            for priority, (taxonomy, concept) in enumerate(spec.members):
                taxonomy_node = facts_node.get(taxonomy)
                if taxonomy_node is None:
                    continue
                if not isinstance(taxonomy_node, dict):
                    raise SecPayloadError(
                        f"SEC Company Facts taxonomy {taxonomy} must be an object."
                    )
                concept_node = taxonomy_node.get(concept)
                if concept_node is None:
                    continue
                if not isinstance(concept_node, dict):
                    raise SecPayloadError(
                        f"SEC Company Facts concept {taxonomy}:{concept} must be an object."
                    )
                units_node = concept_node.get("units")
                if not isinstance(units_node, dict):
                    raise SecPayloadError(
                        f"SEC Company Facts concept {taxonomy}:{concept} is missing units."
                    )
                label = str(concept_node.get("label") or concept).strip()
                description = str(concept_node.get("description") or "").strip()
                for unit in spec.units:
                    rows = units_node.get(unit)
                    if rows is None:
                        continue
                    if not isinstance(rows, list):
                        raise SecPayloadError(
                            f"SEC Company Facts unit {taxonomy}:{concept}/{unit} must be an array."
                        )
                    for record in rows:
                        fact = self._parse_record(
                            record,
                            identity=identity,
                            ticker=ticker,
                            company_name=company_name,
                            spec=spec,
                            taxonomy=taxonomy,
                            concept=concept,
                            concept_priority=priority,
                            label=label,
                            description=description,
                            unit=unit,
                            source_url=url,
                            fetched_at=document.fetched_at,
                            since_date=since_date,
                            filing_index=filing_index,
                        )
                        if fact is None:
                            continue
                        if fact.accession_number not in filing_index:
                            unmatched_accessions.add(fact.accession_number)
                        key = (
                            fact.canonical_name,
                            fact.taxonomy,
                            fact.concept,
                            fact.unit,
                            fact.start_date,
                            fact.end_date,
                            fact.accession_number,
                            fact.form,
                        )
                        existing = normalized.get(key)
                        if existing is not None and existing.value != fact.value:
                            raise SecPayloadError(
                                "SEC Company Facts contains conflicting values for an "
                                f"identical context: {taxonomy}:{concept} "
                                f"{fact.accession_number}"
                            )
                        normalized.setdefault(key, fact)

        values = tuple(
            sorted(
                normalized.values(),
                key=lambda fact: (
                    fact.end_date,
                    fact.start_date or fact.end_date,
                    fact.availability_date,
                    fact.accession_number,
                    fact.canonical_name,
                    -fact.concept_priority,
                ),
                reverse=True,
            )
        )
        present = tuple(
            spec.canonical_name
            for spec in self.concept_specs
            if any(fact.canonical_name == spec.canonical_name for fact in values)
        )
        return SecCompanyFactsSnapshot(
            cik=identity.cik,
            ticker=normalize_sec_ticker(ticker),
            company_name=company_name,
            facts=values,
            source_url=url,
            fetched_at=document.fetched_at,
            cache_hit=document.cache_hit,
            stale=document.stale,
            configured_concepts=tuple(spec.canonical_name for spec in self.concept_specs),
            present_concepts=present,
            unmatched_accessions=len(unmatched_accessions),
        )

    def _parse_record(
        self,
        record: Any,
        *,
        identity: SecCompanyIdentity,
        ticker: str,
        company_name: str,
        spec: SecConceptSpec,
        taxonomy: str,
        concept: str,
        concept_priority: int,
        label: str,
        description: str,
        unit: str,
        source_url: str,
        fetched_at: datetime,
        since_date: date,
        filing_index: dict[str, SecFiling],
    ) -> SecCompanyFact | None:
        if not isinstance(record, dict):
            raise SecPayloadError("SEC Company Facts contains a malformed fact record.")
        form = str(record.get("form") or "").strip().upper()
        if form not in self.forms:
            return None
        filed_date = _parse_date(record.get("filed"), field="filed", required=True)
        assert filed_date is not None
        if filed_date < since_date:
            return None
        accession_number = str(record.get("accn") or "").strip()
        if not ACCESSION_PATTERN.fullmatch(accession_number):
            raise SecPayloadError(
                f"SEC Company Facts contains invalid accession number: {accession_number}"
            )
        end_date = _parse_date(record.get("end"), field="end", required=True)
        assert end_date is not None
        start_date = _parse_date(record.get("start"), field="start", required=False)
        if spec.period_type == "duration" and start_date is None:
            raise SecPayloadError(
                f"SEC duration fact {taxonomy}:{concept} is missing a start date."
            )
        if spec.period_type == "instant" and start_date is not None:
            raise SecPayloadError(
                f"SEC instant fact {taxonomy}:{concept} unexpectedly has a start date."
            )
        raw_value = record.get("val")
        if isinstance(raw_value, bool) or raw_value is None:
            raise SecPayloadError(f"SEC Company Facts {taxonomy}:{concept} has invalid value.")
        try:
            value = Decimal(str(raw_value))
        except (InvalidOperation, ValueError) as exc:
            raise SecPayloadError(
                f"SEC Company Facts {taxonomy}:{concept} has nonnumeric value."
            ) from exc
        if not value.is_finite():
            raise SecPayloadError(f"SEC Company Facts {taxonomy}:{concept} has non-finite value.")
        raw_fiscal_year = record.get("fy")
        try:
            fiscal_year = int(raw_fiscal_year) if raw_fiscal_year not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise SecPayloadError(
                f"SEC Company Facts {taxonomy}:{concept} has invalid fiscal year."
            ) from exc
        fiscal_period = str(record.get("fp") or "").strip().upper() or None
        frame = str(record.get("frame") or "").strip() or None
        filing = filing_index.get(accession_number)
        return SecCompanyFact(
            cik=identity.cik,
            ticker=normalize_sec_ticker(ticker),
            company_name=company_name,
            canonical_name=spec.canonical_name,
            taxonomy=taxonomy,
            concept=concept,
            concept_priority=concept_priority,
            label=label,
            description=description,
            period_type=spec.period_type,
            unit=unit,
            value=value,
            start_date=start_date,
            end_date=end_date,
            accession_number=accession_number,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            form=form,
            filed_date=filed_date,
            frame=frame,
            accepted_at=filing.accepted_at if filing else None,
            availability_date=filing.availability_date if filing else filed_date,
            availability_precision=filing.availability_precision if filing else "date",
            source_url=source_url,
            fetched_at=fetched_at,
        )

    @staticmethod
    def effective_facts(
        facts: tuple[SecCompanyFact, ...], *, available_at: datetime | None = None
    ) -> tuple[SecCompanyFact, ...]:
        if available_at is not None and available_at.tzinfo is None:
            raise ValueError("SEC fact available_at cutoff must include a timezone.")
        selected: dict[tuple[str, str, date | None, date], SecCompanyFact] = {}
        for fact in facts:
            if available_at is not None:
                if fact.accepted_at and fact.accepted_at > available_at:
                    continue
                if not fact.accepted_at and fact.availability_date > available_at.date():
                    continue
            key = (fact.canonical_name, fact.unit, fact.start_date, fact.end_date)
            current = selected.get(key)
            if current is None or SecCompanyFacts._selection_order(fact) > (
                SecCompanyFacts._selection_order(current)
            ):
                selected[key] = fact
        return tuple(
            sorted(
                selected.values(),
                key=lambda fact: (
                    fact.end_date,
                    fact.start_date or fact.end_date,
                    fact.canonical_name,
                ),
                reverse=True,
            )
        )

    @staticmethod
    def _selection_order(fact: SecCompanyFact) -> tuple[Any, ...]:
        available = fact.accepted_at or datetime.combine(
            fact.availability_date, datetime_time.min, tzinfo=UTC
        )
        return (available, fact.accession_number, -fact.concept_priority)
