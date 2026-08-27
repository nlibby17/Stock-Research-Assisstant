from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stockrank.config import load_settings
from stockrank.data.sec import (
    SecClient,
    SecCompanyFacts,
    SecCompanyIdentity,
    SecError,
    SecIdentityDirectory,
    SecSubmissions,
    load_sec_concept_specs,
    load_sec_entity_overrides,
    normalize_sec_ticker,
)
from stockrank.models import ProviderHealth
from stockrank.pipeline import run_analysis
from stockrank.reporting import write_report_bundle
from stockrank.research import normalize_research, validate_research
from stockrank.storage import Storage


def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def command_run(args: argparse.Namespace) -> int:
    settings = load_settings()
    run_id, report_path, warnings = run_analysis(settings, demo=args.demo, force=args.force)
    print(f"Run: {run_id}")
    print(f"Report: {report_path}")
    print(f"Warnings: {len(warnings)}")
    return command_validate(argparse.Namespace())


def command_validate(_: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    run = storage.latest_run()
    if not run:
        print("No analysis run exists.")
        return 1
    results = storage.get_results(run["run_id"])
    priced = sum(result["latest_price"] is not None for result in results)
    eligible = sum(result["eligible"] for result in results)
    sparse = sum(
        result["overall_coverage"] < float(settings.raw["app"]["minimum_overall_coverage"])
        for result in results
    )
    warnings = json.loads(run["warnings_json"])
    print(
        f"Latest run {run['run_id']} | status={run['status']} | as_of={run['as_of']} | "
        f"provider={run['provider']} | model={run['model_version']}"
    )
    print(
        f"Universe={len(results)} | priced={priced} | eligible={eligible} | "
        f"below_coverage_threshold={sparse} | warnings={len(warnings)}"
    )
    if run["provider"] == "demo-synthetic":
        print("DATA LABEL: SYNTHETIC DEMO — not suitable for investment research")
    for warning in warnings[:10]:
        print(f"WARNING: {warning}")
    if len(warnings) > 10:
        print(f"WARNING: {len(warnings) - 10} additional warnings are in the report/database")
    return 0 if run["status"] == "completed" and priced else 1


def command_research_import(args: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    errors = validate_research(payload, storage)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    payload = normalize_research(payload)
    storage.import_research(payload["run_id"], payload)
    report = write_report_bundle(settings, storage, payload["run_id"])
    print(f"Imported researched notes and refreshed report: {report}")
    return 0


def command_storage_status(_: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    sizes = {
        "database": sum(
            _file_size(Path(str(settings.database_path) + suffix))
            for suffix in ("", "-wal", "-shm")
        ),
        "reports": sum(
            path.stat().st_size
            for path in (settings.runtime_dir / "reports").glob("**/*")
            if path.is_file()
        )
        if (settings.runtime_dir / "reports").exists()
        else 0,
        "sec_cache": sum(
            path.stat().st_size
            for path in (settings.runtime_dir / "cache" / "sec").glob("**/*")
            if path.is_file()
        )
        if (settings.runtime_dir / "cache" / "sec").exists()
        else 0,
        "logs": sum(
            path.stat().st_size
            for path in (settings.runtime_dir / "logs").glob("**/*")
            if path.is_file()
        )
        if (settings.runtime_dir / "logs").exists()
        else 0,
        "temporary": sum(
            path.stat().st_size
            for path in (settings.runtime_dir / "tmp").glob("**/*")
            if path.is_file()
        )
        if (settings.runtime_dir / "tmp").exists()
        else 0,
    }
    for name, size in sizes.items():
        print(f"{name}: {_human_bytes(size)}")
    print(f"total: {_human_bytes(sum(sizes.values()))}")
    for table, count in storage.counts().items():
        print(f"{table}: {count} rows")
    return 0


def command_storage_clean(args: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    apply = bool(args.apply)
    preview = storage.cleanup_database(
        int(settings.raw["retention"]["price_history_days"]), apply=apply
    )
    report_cutoff = datetime.now(UTC) - timedelta(
        days=int(settings.raw["retention"]["report_days"])
    )
    temp_cutoff = datetime.now(UTC) - timedelta(
        days=int(settings.raw["retention"]["temporary_file_days"])
    )
    sec_cache_cutoff = datetime.now(UTC) - timedelta(
        hours=float(settings.raw.get("sec", {}).get("maximum_stale_cache_hours", 168.0))
    )
    candidates: list[Path] = []
    for directory, cutoff, keep_names in (
        (settings.runtime_dir / "reports", report_cutoff, {"latest.md", "research_template.json"}),
        (settings.runtime_dir / "tmp", temp_cutoff, set()),
        (settings.runtime_dir / "cache" / "sec", sec_cache_cutoff, set()),
    ):
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.name not in keep_names:
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                if modified < cutoff:
                    candidates.append(path)
    print(("Applied" if apply else "Dry run") + " database cleanup: " + json.dumps(preview))
    print(f"Expired runtime files: {len(candidates)}")
    for path in candidates:
        print(f"  {path}")
        if apply:
            path.unlink()
    if not apply:
        print(
            "Nothing was removed. Re-run with --apply to perform this exact policy-based cleanup."
        )
    return 0


def command_sec_health(args: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    endpoint = str(settings.raw.get("sec", {}).get("identity_url", ""))
    started = time.perf_counter()
    checked_at = datetime.now(UTC)
    try:
        directory = SecIdentityDirectory.from_settings(settings)
        snapshot = directory.fetch(force=bool(args.force))
        index = directory.index_by_ticker(snapshot.identities)
        matched = [
            security.ticker
            for security in settings.universe
            if normalize_sec_ticker(security.ticker) in index
        ]
        missing = [security.ticker for security in settings.universe if security.ticker not in matched]
        status = "healthy" if not missing and not snapshot.stale else "degraded"
        details = [
            f"identity_records={len(snapshot.identities)}",
            f"universe_matches={len(matched)}/{len(settings.universe)}",
        ]
        if missing:
            details.append("missing=" + ",".join(missing))
        if snapshot.stale:
            details.append("stale_cache_fallback=true")
        latency_ms = (time.perf_counter() - started) * 1000
        health = ProviderHealth(
            provider="sec-edgar",
            checked_at=checked_at,
            status=status,
            endpoint=snapshot.source_url,
            latency_ms=latency_ms,
            cache_hit=snapshot.cache_hit,
            detail="; ".join(details),
        )
        storage.record_provider_health(health)
        print(
            f"SEC provider: {status} | identities={len(snapshot.identities)} | "
            f"universe={len(matched)}/{len(settings.universe)} | "
            f"cache={'stale' if snapshot.stale else 'hit' if snapshot.cache_hit else 'miss'} | "
            f"latency={latency_ms:.0f}ms"
        )
        if missing:
            print("Unmatched universe tickers: " + ", ".join(missing))
        print(f"Source: {snapshot.source_url}")
        print(f"Fetched at: {snapshot.fetched_at.isoformat()}")
        return 0 if status == "healthy" else 1
    except SecError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        storage.record_provider_health(
            ProviderHealth(
                provider="sec-edgar",
                checked_at=checked_at,
                status="unavailable",
                endpoint=endpoint,
                latency_ms=latency_ms,
                cache_hit=False,
                detail=str(exc),
            )
        )
        print(f"SEC provider: unavailable | {exc}", file=sys.stderr)
        return 2


def _years_ago(value: datetime, years: int) -> datetime:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def command_sec_filings_sync(args: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    years = int(args.years or settings.raw.get("sec", {}).get("filing_history_years", 5))
    if years <= 0:
        print("ERROR: --years must be greater than zero.", file=sys.stderr)
        return 2
    since_date = _years_ago(datetime.now(UTC), years).date()
    requested = {
        normalize_sec_ticker(ticker)
        for raw in (args.ticker or [])
        for ticker in raw.split(",")
        if ticker.strip()
    }
    universe_by_ticker = {
        normalize_sec_ticker(security.ticker): security for security in settings.universe
    }
    unknown = sorted(requested - universe_by_ticker.keys())
    if unknown:
        print("ERROR: ticker(s) are not in the configured universe: " + ", ".join(unknown))
        return 2
    selected = [
        security
        for ticker, security in universe_by_ticker.items()
        if not requested or ticker in requested
    ]
    started = time.perf_counter()
    checked_at = datetime.now(UTC)
    failures: list[str] = []
    stale_tickers: list[str] = []
    synced = 0
    stored_count = 0
    annual_coverage = 0
    quarterly_coverage = 0
    effective_count = 0
    cache_hits = 0
    request_count = 0
    endpoint = "https://data.sec.gov/submissions/CIK##########.json"
    try:
        client = SecClient.from_settings(settings)
        identity_directory = SecIdentityDirectory.from_settings(settings, client)
        identity_snapshot = identity_directory.fetch(force=bool(args.force))
        identities = identity_directory.index_by_ticker(identity_snapshot.identities)
        submissions = SecSubmissions.from_settings(settings, client)
        entity_overrides = load_sec_entity_overrides(settings)
    except SecError as exc:
        failures.append(f"identity setup: {exc}")
        identities = {}
        submissions = None
        entity_overrides = {}

    for security in selected:
        ticker = normalize_sec_ticker(security.ticker)
        identity = identities.get(ticker)
        if not identity:
            failures.append(f"{ticker}: no SEC identity")
            continue
        sync_identities = [identity]
        for additional_cik in entity_overrides.get(ticker, ()):
            if additional_cik == identity.cik:
                continue
            sync_identities.append(
                SecCompanyIdentity(
                    cik=additional_cik,
                    name=f"{identity.name} predecessor",
                    ticker=ticker,
                    exchange=identity.exchange,
                )
            )
        ticker_filings = {}
        ticker_snapshots = []
        try:
            assert submissions is not None
            for sync_identity in sync_identities:
                snapshot = submissions.fetch(
                    sync_identity,
                    ticker=ticker,
                    since_date=since_date,
                    force=bool(args.force),
                )
                ticker_snapshots.append(snapshot)
                for filing in snapshot.filings:
                    ticker_filings[(filing.cik, filing.accession_number)] = filing
            storage.replace_sec_filings(
                ticker=ticker,
                ciks=[value.cik for value in sync_identities],
                since_date=since_date,
                filings=ticker_filings.values(),
            )
        except SecError as exc:
            failures.append(f"{ticker}: {exc}")
            continue
        synced += 1
        stored_count += len(ticker_filings)
        effective = submissions.effective_filings(tuple(ticker_filings.values()))
        effective_count += len(effective)
        annual_coverage += any(filing.base_form == "10-K" for filing in effective)
        quarterly_coverage += any(filing.base_form == "10-Q" for filing in effective)
        cache_hits += sum(snapshot.cache_hits for snapshot in ticker_snapshots)
        request_count += sum(snapshot.request_count for snapshot in ticker_snapshots)
        if any(snapshot.stale for snapshot in ticker_snapshots):
            stale_tickers.append(ticker)

    status = (
        "healthy"
        if synced == len(selected)
        and annual_coverage == len(selected)
        and quarterly_coverage == len(selected)
        and not stale_tickers
        else "degraded"
    )
    latency_ms = (time.perf_counter() - started) * 1000
    details = [
        f"companies={synced}/{len(selected)}",
        f"filings={stored_count}",
        f"effective={effective_count}",
        f"annual_coverage={annual_coverage}/{len(selected)}",
        f"quarterly_coverage={quarterly_coverage}/{len(selected)}",
        f"since={since_date.isoformat()}",
    ]
    if stale_tickers:
        details.append("stale=" + ",".join(stale_tickers))
    if failures:
        details.append(f"failures={len(failures)}")
    full_universe_sync = len(selected) == len(settings.universe)
    health_status = status if full_universe_sync else "partial"
    details.append(f"scope={len(selected)}/{len(settings.universe)}")
    storage.record_provider_health(
        ProviderHealth(
            provider="sec-submissions",
            checked_at=checked_at,
            status=health_status if synced else "unavailable",
            endpoint=endpoint,
            latency_ms=latency_ms,
            cache_hit=bool(request_count and cache_hits == request_count),
            detail="; ".join(details),
        )
    )
    print(
        f"SEC filings: {status if synced else 'unavailable'} | "
        f"companies={synced}/{len(selected)} | filings={stored_count} | "
        f"effective={effective_count} | 10-K={annual_coverage}/{len(selected)} | "
        f"10-Q={quarterly_coverage}/{len(selected)} | since={since_date.isoformat()} | "
        f"latency={latency_ms:.0f}ms"
    )
    print(f"Requests: {request_count} | cache hits: {cache_hits}")
    for failure in failures[:10]:
        print(f"WARNING: {failure}")
    if len(failures) > 10:
        print(f"WARNING: {len(failures) - 10} additional failures were recorded")
    return 0 if status == "healthy" else 1


def command_sec_filings_status(_: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    health = storage.get_provider_health("sec-submissions")
    if not health:
        print("No SEC filing sync has been recorded. Run stockrank sec-filings-sync.")
        return 1
    tickers = [normalize_sec_ticker(security.ticker) for security in settings.universe]
    with_annual = 0
    with_quarterly = 0
    filing_count = 0
    for ticker in tickers:
        filings = storage.get_sec_filings(ticker)
        filing_count += len(filings)
        effective = SecSubmissions.effective_filings(tuple(filings))
        with_annual += any(filing.base_form == "10-K" for filing in effective)
        with_quarterly += any(filing.base_form == "10-Q" for filing in effective)
    print(
        f"SEC filings stored={filing_count} | 10-K coverage={with_annual}/{len(tickers)} | "
        f"10-Q coverage={with_quarterly}/{len(tickers)}"
    )
    status = (
        "healthy"
        if health.status == "healthy"
        and with_annual == len(tickers)
        and with_quarterly == len(tickers)
        else "partial"
    )
    print(
        f"Latest sync: {status} | checked={health.checked_at.isoformat()} | "
        f"{health.detail}"
    )
    return 0 if status == "healthy" else 1


def command_sec_facts_sync(args: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    sec_config = settings.raw.get("sec", {})
    years = int(args.years or sec_config.get("companyfacts_history_years", 5))
    if years <= 0:
        print("ERROR: --years must be greater than zero.", file=sys.stderr)
        return 2
    since_date = _years_ago(datetime.now(UTC), years).date()
    requested = {
        normalize_sec_ticker(ticker)
        for raw in (args.ticker or [])
        for ticker in raw.split(",")
        if ticker.strip()
    }
    universe_by_ticker = {
        normalize_sec_ticker(security.ticker): security for security in settings.universe
    }
    unknown = sorted(requested - universe_by_ticker.keys())
    if unknown:
        print("ERROR: ticker(s) are not in the configured universe: " + ", ".join(unknown))
        return 2
    selected = [
        security
        for ticker, security in universe_by_ticker.items()
        if not requested or ticker in requested
    ]
    core_concepts = tuple(
        str(value)
        for value in sec_config.get(
            "companyfacts_core_concepts",
            ("revenue", "net_income", "operating_cash_flow", "assets"),
        )
    )
    started = time.perf_counter()
    checked_at = datetime.now(UTC)
    failures: list[str] = []
    stale_tickers: list[str] = []
    synced = 0
    stored_count = 0
    effective_count = 0
    full_core_coverage = 0
    concept_names = core_concepts
    cache_hits = 0
    request_count = 0
    unmatched_accessions = 0
    endpoint = "https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json"
    try:
        client = SecClient.from_settings(settings)
        directory = SecIdentityDirectory.from_settings(settings, client)
        identity_snapshot = directory.fetch(force=bool(args.force))
        identities = directory.index_by_ticker(identity_snapshot.identities)
        companyfacts = SecCompanyFacts.from_settings(settings, client)
        concept_names = tuple(spec.canonical_name for spec in companyfacts.concept_specs)
        unknown_core = sorted(set(core_concepts) - set(concept_names))
        if unknown_core:
            raise SecError(
                "SEC Company Facts core concepts are not configured: "
                + ", ".join(unknown_core)
            )
        entity_overrides = load_sec_entity_overrides(settings)
    except SecError as exc:
        failures.append(f"Company Facts setup: {exc}")
        identities = {}
        companyfacts = None
        entity_overrides = {}
    concept_coverage = {concept: 0 for concept in concept_names}

    for security in selected:
        ticker = normalize_sec_ticker(security.ticker)
        identity = identities.get(ticker)
        if not identity:
            failures.append(f"{ticker}: no SEC identity")
            continue
        sync_identities = [identity]
        for additional_cik in entity_overrides.get(ticker, ()):
            if additional_cik != identity.cik:
                sync_identities.append(
                    SecCompanyIdentity(
                        cik=additional_cik,
                        name=f"{identity.name} predecessor",
                        ticker=ticker,
                        exchange=identity.exchange,
                    )
                )
        filings = tuple(storage.get_sec_filings(ticker, since_date=since_date))
        if not filings:
            failures.append(f"{ticker}: no stored SEC filings; run sec-filings-sync first")
            continue
        ticker_facts = {}
        snapshots = []
        try:
            assert companyfacts is not None
            for sync_identity in sync_identities:
                snapshot = companyfacts.fetch(
                    sync_identity,
                    ticker=ticker,
                    since_date=since_date,
                    filings=filings,
                    force=bool(args.force),
                )
                snapshots.append(snapshot)
                for fact in snapshot.facts:
                    key = (
                        fact.cik,
                        fact.canonical_name,
                        fact.taxonomy,
                        fact.concept,
                        fact.unit,
                        fact.start_date,
                        fact.end_date,
                        fact.accession_number,
                    )
                    ticker_facts[key] = fact
            storage.replace_sec_company_facts(
                ticker=ticker,
                ciks=[value.cik for value in sync_identities],
                since_date=since_date,
                facts=ticker_facts.values(),
            )
        except SecError as exc:
            failures.append(f"{ticker}: {exc}")
            continue
        synced += 1
        stored_count += len(ticker_facts)
        effective = companyfacts.effective_facts(tuple(ticker_facts.values()))
        effective_count += len(effective)
        present = {fact.canonical_name for fact in effective}
        for concept in concept_names:
            concept_coverage[concept] += concept in present
        full_core_coverage += all(concept in present for concept in core_concepts)
        cache_hits += sum(snapshot.cache_hit for snapshot in snapshots)
        request_count += len(snapshots)
        unmatched_accessions += sum(snapshot.unmatched_accessions for snapshot in snapshots)
        if any(snapshot.stale for snapshot in snapshots):
            stale_tickers.append(ticker)

    status = (
        "healthy"
        if synced == len(selected)
        and full_core_coverage == len(selected)
        and not stale_tickers
        and unmatched_accessions == 0
        else "degraded"
    )
    latency_ms = (time.perf_counter() - started) * 1000
    details = [
        f"companies={synced}/{len(selected)}",
        f"facts={stored_count}",
        f"effective={effective_count}",
        f"core_complete={full_core_coverage}/{len(selected)}",
        f"since={since_date.isoformat()}",
    ]
    details.extend(
        f"{concept}={coverage}/{len(selected)}"
        for concept, coverage in concept_coverage.items()
    )
    if unmatched_accessions:
        details.append(f"date_only_accessions={unmatched_accessions}")
    if stale_tickers:
        details.append("stale=" + ",".join(stale_tickers))
    if failures:
        details.append(f"failures={len(failures)}")
    full_universe_sync = len(selected) == len(settings.universe)
    health_status = status if full_universe_sync else "partial"
    details.append(f"scope={len(selected)}/{len(settings.universe)}")
    storage.record_provider_health(
        ProviderHealth(
            provider="sec-companyfacts",
            checked_at=checked_at,
            status=health_status if synced else "unavailable",
            endpoint=endpoint,
            latency_ms=latency_ms,
            cache_hit=bool(request_count and cache_hits == request_count),
            detail="; ".join(details),
        )
    )
    print(
        f"SEC Company Facts: {status if synced else 'unavailable'} | "
        f"companies={synced}/{len(selected)} | facts={stored_count} | "
        f"effective={effective_count} | core={full_core_coverage}/{len(selected)} | "
        f"since={since_date.isoformat()} | latency={latency_ms:.0f}ms"
    )
    print(f"Requests: {request_count} | cache hits: {cache_hits}")
    for concept, coverage in concept_coverage.items():
        print(f"  {concept}: {coverage}/{len(selected)}")
    if unmatched_accessions:
        print(f"WARNING: {unmatched_accessions} accession(s) use date-only availability")
    for failure in failures[:10]:
        print(f"WARNING: {failure}")
    if len(failures) > 10:
        print(f"WARNING: {len(failures) - 10} additional failures were recorded")
    return 0 if status == "healthy" else 1


def command_sec_facts_status(_: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    health = storage.get_provider_health("sec-companyfacts")
    if not health:
        print("No SEC Company Facts sync has been recorded. Run stockrank sec-facts-sync.")
        return 1
    tickers = [normalize_sec_ticker(security.ticker) for security in settings.universe]
    core_concepts = tuple(
        str(value)
        for value in settings.raw.get("sec", {}).get("companyfacts_core_concepts", ())
    )
    concept_names = tuple(spec.canonical_name for spec in load_sec_concept_specs(settings))
    concept_coverage = {concept: 0 for concept in concept_names}
    fact_count = 0
    complete = 0
    for ticker in tickers:
        facts = SecCompanyFacts.effective_facts(
            tuple(storage.get_sec_company_facts(ticker))
        )
        fact_count += len(facts)
        present = {fact.canonical_name for fact in facts}
        for concept in concept_names:
            concept_coverage[concept] += concept in present
        complete += all(concept in present for concept in core_concepts)
    print(
        f"SEC Company Facts effective={fact_count} | "
        f"core coverage={complete}/{len(tickers)}"
    )
    print("Concept coverage:")
    for key, value in concept_coverage.items():
        print(f"  {key}: {value}/{len(tickers)}")
    status = (
        "healthy"
        if health.status == "healthy" and complete == len(tickers)
        else "partial"
    )
    print(f"Latest sync: {status} | checked={health.checked_at.isoformat()} | {health.detail}")
    return 0 if status == "healthy" else 1


def command_dashboard(_: argparse.Namespace) -> int:
    dashboard_path = Path(__file__).with_name("dashboard.py")
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(dashboard_path)])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stockrank", description="Local research-only stock ranking application"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Retrieve, calculate, rank, and report")
    run_parser.add_argument("--demo", action="store_true", help="Use explicit synthetic demo data")
    run_parser.add_argument("--force", action="store_true", help="Bypass fresh-cache checks")
    run_parser.set_defaults(handler=command_run)
    validate_parser = subparsers.add_parser("validate-latest", help="Validate latest run quality")
    validate_parser.set_defaults(handler=command_validate)
    research_parser = subparsers.add_parser(
        "research-import", help="Validate/import Codex research JSON"
    )
    research_parser.add_argument("--file", required=True)
    research_parser.set_defaults(handler=command_research_import)
    status_parser = subparsers.add_parser("storage-status", help="Inspect runtime storage")
    status_parser.set_defaults(handler=command_storage_status)
    clean_parser = subparsers.add_parser("storage-clean", help="Preview/apply retention cleanup")
    clean_parser.add_argument("--apply", action="store_true")
    clean_parser.set_defaults(handler=command_storage_clean)
    sec_health_parser = subparsers.add_parser(
        "sec-health", help="Verify SEC identity coverage and provider health"
    )
    sec_health_parser.add_argument(
        "--force", action="store_true", help="Bypass the SEC identity cache"
    )
    sec_health_parser.set_defaults(handler=command_sec_health)
    filing_sync_parser = subparsers.add_parser(
        "sec-filings-sync", help="Sync normalized SEC 10-K/10-Q filing metadata"
    )
    filing_sync_parser.add_argument(
        "--force", action="store_true", help="Bypass SEC submissions caches"
    )
    filing_sync_parser.add_argument(
        "--years", type=int, help="Override the configured filing-history window"
    )
    filing_sync_parser.add_argument(
        "--ticker",
        action="append",
        help="Limit sync to a universe ticker; repeat or use comma-separated values",
    )
    filing_sync_parser.set_defaults(handler=command_sec_filings_sync)
    filing_status_parser = subparsers.add_parser(
        "sec-filings-status", help="Inspect stored SEC filing coverage"
    )
    filing_status_parser.set_defaults(handler=command_sec_filings_status)
    fact_sync_parser = subparsers.add_parser(
        "sec-facts-sync", help="Sync normalized SEC Company Facts/XBRL data"
    )
    fact_sync_parser.add_argument(
        "--force", action="store_true", help="Bypass SEC Company Facts caches"
    )
    fact_sync_parser.add_argument(
        "--years", type=int, help="Override the configured Company Facts history window"
    )
    fact_sync_parser.add_argument(
        "--ticker",
        action="append",
        help="Limit sync to a universe ticker; repeat or use comma-separated values",
    )
    fact_sync_parser.set_defaults(handler=command_sec_facts_sync)
    fact_status_parser = subparsers.add_parser(
        "sec-facts-status", help="Inspect normalized SEC Company Facts coverage"
    )
    fact_status_parser.set_defaults(handler=command_sec_facts_status)
    dashboard_parser = subparsers.add_parser(
        "dashboard", help="Launch the local Streamlit dashboard"
    )
    dashboard_parser.set_defaults(handler=command_dashboard)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
