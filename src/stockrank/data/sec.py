from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import requests

from stockrank.models import SecFiling

if TYPE_CHECKING:
    from stockrank.config import Settings

SEC_IDENTITY_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_ALLOWED_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
SEC_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
EMAIL_PATTERN = re.compile(r"(?<!\S)[^@\s]+@[^@\s]+\.[^@\s]+(?!\S)")
ACCESSION_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")
SUBMISSION_FILE_PATTERN = re.compile(r"^CIK\d{10}-submissions-\d{3}\.json$")
SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"


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
    request_count: int
    stale: bool


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


def load_sec_entity_overrides(settings: Settings) -> dict[str, tuple[str, ...]]:
    configured_path = settings.raw.get("sec", {}).get(
        "entity_overrides_path", "config/sec_entity_overrides.toml"
    )
    path = Path(str(configured_path))
    if not path.is_absolute():
        path = settings.root / path
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
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
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("source_url") != url:
                return None
            return SecJsonDocument(
                payload=record["payload"],
                source_url=url,
                fetched_at=datetime.fromisoformat(record["fetched_at"]),
                cache_hit=True,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write_cache(
        self, url: str, cache_key: str, fetched_at: datetime, payload: Any
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(url, cache_key)
        temp_path = path.with_suffix(".tmp")
        record = {
            "schema_version": 1,
            "source_url": url,
            "fetched_at": fetched_at.isoformat(),
            "payload": payload,
        }
        temp_path.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
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
    directory = (
        f"https://www.sec.gov/Archives/edgar/data/{archive_cik}/{accession_compact}"
    )
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
    def from_settings(
        cls, settings: Settings, client: SecClient | None = None
    ) -> SecSubmissions:
        config = settings.raw.get("sec", {})
        return cls(
            client or SecClient.from_settings(settings),
            cache_ttl_hours=float(config.get("submissions_cache_ttl_hours", 6.0)),
            forms=tuple(
                str(form)
                for form in config.get(
                    "filing_forms", ("10-K", "10-K/A", "10-Q", "10-Q/A")
                )
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
            request_count=len(documents),
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
            primary_document = (
                self._column_value(payload, "primaryDocument", index) or None
            )
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
                    current.accepted_at
                    or datetime.combine(current.filing_date, datetime_time.min, tzinfo=UTC)
                ),
                current.accession_number,
            ) if current else None
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
