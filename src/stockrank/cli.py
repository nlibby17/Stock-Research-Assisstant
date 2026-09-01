from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from stockrank.command_parser import build_command_parser
from stockrank.config import TICKER_PATTERN, Settings, load_settings, validate_settings
from stockrank.customization import (
    HORIZONS,
    PROFILE_NAMES,
    RISK_LEVELS,
    PersonalizationUpdateError,
    enrich_universe,
    model_identifier,
    parse_component_weights,
    parse_tickers,
    profile_weights,
    read_universe_input,
    reset_local_customization,
    save_local_customization,
    universe_identifier,
)
from stockrank.daily_workflow import launch_dashboard, run_daily_workflow
from stockrank.data import YFinanceProvider
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
    validate_sec_configuration,
)
from stockrank.models import (
    ProviderComparisonRun,
    ProviderHealth,
    SecCompanyFactsRefreshState,
    SecFinancialMetric,
    SecFinancialSnapshot,
    Security,
)
from stockrank.pipeline import run_analysis
from stockrank.provider_comparison import (
    compare_provider_metrics,
    load_provider_comparison_config,
)
from stockrank.reporting import write_report_bundle
from stockrank.research import normalize_research, validate_research
from stockrank.sec_financials import FORMULA_VERSION, SecFinancialCalculator
from stockrank.sec_refresh import (
    CompanyFactsRefreshPolicy,
    companyfacts_config_fingerprint,
    decide_companyfacts_refresh,
    filing_fingerprint,
    identity_fingerprint,
    latest_filing_at,
)
from stockrank.storage import PROVIDER_EVIDENCE_MAX_LINK_AGE_HOURS, Storage


def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _check_pyarrow_import() -> tuple[str | None, str | None]:
    """Check the native extension in a child process so a crash cannot kill this command."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import pyarrow; print(pyarrow.__version__)",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "PyArrow native import check timed out after 30 seconds", None
    except OSError as exc:
        return f"PyArrow native import check could not start: {exc}", None
    if result.returncode != 0:
        if result.returncode < 0:
            detail = f"terminated by signal {-result.returncode}"
        else:
            stderr_lines = result.stderr.strip().splitlines()
            detail = stderr_lines[-1] if stderr_lines else f"exit code {result.returncode}"
        return (
            (
                "PyArrow native import check failed "
                f"({detail}). Rerun the platform setup or update helper before using the app"
            ),
            None,
        )
    version = result.stdout.strip().splitlines()
    return None, version[-1] if version else "version unavailable"


def command_setup_check(_: argparse.Namespace) -> int:
    """Verify that a cloned checkout can initialize its local runtime safely."""
    failures: list[str] = []
    try:
        settings = load_settings()
    except (OSError, KeyError, ValueError) as exc:
        print(f"ERROR: configuration could not be loaded: {exc}", file=sys.stderr)
        return 1

    required_paths = (
        settings.root / "config" / "preferences.toml",
        settings.root / str(settings.raw["universe"]["path"]),
    )
    for path in required_paths:
        if not path.is_file():
            failures.append(f"Required project file is missing: {path}")
    config_errors, config_warnings = validate_settings(settings)
    failures.extend(config_errors)

    pyarrow_failure, pyarrow_version = _check_pyarrow_import()
    if pyarrow_failure:
        failures.append(pyarrow_failure)

    failures.extend(validate_sec_configuration(settings))

    try:
        storage = Storage(settings.database_path)
        storage.initialize()
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.runtime_dir, prefix="setup-check-"):
            pass
    except OSError as exc:
        failures.append(f"Runtime directory is not writable: {exc}")

    print(
        f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
        f"PyArrow: {pyarrow_version or 'unavailable'} | project: {settings.root}"
    )
    print(
        f"Universe: {len(settings.universe)} securities | model: {settings.model_version} | "
        f"profile: {settings.profile_name} | runtime: {settings.runtime_dir}"
    )
    for warning in config_warnings:
        print(f"WARNING: {warning}")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        print("Setup check: NOT READY")
        return 1
    print("Setup check: READY")
    return 0


def command_config_check(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except (OSError, KeyError, ValueError) as exc:
        print(f"Configuration check: INVALID | {exc}", file=sys.stderr)
        return 1
    errors, warnings = validate_settings(settings)
    errors.extend(validate_sec_configuration(settings))
    print(
        f"Configuration: {'local profile' if settings.uses_local_preferences else 'project default'} | "
        f"profile={settings.profile_name} | horizon={settings.investment_horizon} | "
        f"risk={settings.risk_tolerance}"
    )
    print(
        f"Universe={settings.raw['universe']['name']} ({len(settings.universe)} stocks) | "
        f"model={settings.model_version}"
    )
    print(
        "Component weights: "
        + ", ".join(
            f"{component}={weight:.1%}" for component, weight in settings.component_weights.items()
        )
    )
    validity = settings.raw["scoring"]["validity"]
    print(
        f"Scoring validity: minimum peers={validity['minimum_metric_peer_count']} | "
        f"debt/equity minimum={float(validity['minimum_debt_to_equity']):g} | "
        f"ROE maximum={float(validity['maximum_return_on_equity']):.0%}"
    )
    eligibility = settings.raw["scoring"]["eligibility"]
    print(
        "Candidate liquidity: "
        f"minimum price={float(eligibility['minimum_latest_price']):.2f} | "
        "minimum 20-day average dollar volume="
        f"{float(eligibility['minimum_average_dollar_volume_20d']):,.0f}"
    )
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print("Configuration check: INVALID")
        return 1
    if not bool(getattr(args, "live", False)):
        print("Configuration check: VALID (local checks only)")
        print("Use `stockrank config-check --live` for Yahoo price and SEC identity coverage.")
        return 0

    provider = YFinanceProvider(
        retries=int(settings.raw["provider"]["request_retries"]),
        backoff_seconds=float(settings.raw["provider"]["retry_backoff_seconds"]),
    )
    today = datetime.now(UTC).date()
    try:
        price_data, price_warnings = provider.fetch_prices(
            list(settings.universe), today - timedelta(days=14), today + timedelta(days=1)
        )
    except Exception as exc:  # noqa: BLE001 - provider exceptions vary.
        print(f"ERROR: Yahoo price validation failed: {exc}", file=sys.stderr)
        return 1
    covered = sum(bool(price_data.get(security.ticker)) for security in settings.universe)
    print(f"Yahoo price coverage: {covered}/{len(settings.universe)}")
    for warning in price_warnings:
        print(f"WARNING: {warning}")
    sec_result = command_sec_health(argparse.Namespace(force=False))
    if covered != len(settings.universe) or sec_result:
        print("Configuration check: PROVIDER ATTENTION REQUIRED")
        return 1
    print("Configuration check: VALID, including live provider coverage")
    return 0


def _prompt(label: str, current: str) -> str:
    value = input(f"{label} [{current}]: ").strip()
    return value or current


def _prompt_choice(label: str, current: str, choices: tuple[str, ...]) -> str:
    while True:
        value = _prompt(f"{label} ({'/'.join(choices)})", current).lower()
        if value in choices:
            return value
        print("Please choose one of: " + ", ".join(choices))


def command_configure(args: argparse.Namespace) -> int:
    root = Path.cwd().resolve()
    if bool(args.reset):
        try:
            backups = reset_local_customization(root)
        except PersonalizationUpdateError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        if backups:
            print("Default configuration restored. Backups:")
            for backup in backups:
                print(f"  {backup}")
        else:
            print("Default configuration was already active; no local files changed.")
        return command_config_check(argparse.Namespace(live=False))

    try:
        current = load_settings(root)
    except (OSError, KeyError, ValueError) as exc:
        print(f"WARNING: current local configuration is invalid ({exc}); using project defaults")
        current = load_settings(root, root / "config" / "preferences.toml")
    interactive = not bool(args.yes)
    profile = args.profile or (
        _prompt_choice("Ranking profile", current.profile_name, PROFILE_NAMES)
        if interactive
        else current.profile_name
    )
    horizon = args.horizon or (
        _prompt_choice("Investment horizon", current.investment_horizon, HORIZONS)
        if interactive
        else current.investment_horizon
    )
    risk = args.risk or (
        _prompt_choice("Risk tolerance", current.risk_tolerance, RISK_LEVELS)
        if interactive
        else current.risk_tolerance
    )
    try:
        weights = (
            parse_component_weights(args.weights)
            if args.weights
            else profile_weights(profile, risk, horizon)
        )
        weights = {component: round(weight, 12) for component, weight in weights.items()}
        candidate_limit = int(
            args.candidate_limit
            if args.candidate_limit is not None
            else _prompt("Top-candidate limit", str(current.raw["app"]["top_candidate_limit"]))
            if interactive
            else current.raw["app"]["top_candidate_limit"]
        )
        minimum_score = float(
            args.minimum_score
            if args.minimum_score is not None
            else _prompt(
                "Minimum candidate score", str(current.raw["app"]["minimum_candidate_score"])
            )
            if interactive
            else current.raw["app"]["minimum_candidate_score"]
        )
        minimum_coverage = float(
            args.minimum_coverage
            if args.minimum_coverage is not None
            else _prompt(
                "Minimum data coverage (0-1)",
                str(current.raw["app"]["minimum_overall_coverage"]),
            )
            if interactive
            else current.raw["app"]["minimum_overall_coverage"]
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    requested_universe = None
    use_default_universe = bool(getattr(args, "use_default_universe", False))
    if args.tickers:
        requested_universe = [Security(ticker, "", "") for ticker in parse_tickers(args.tickers)]
    elif args.universe_file:
        try:
            requested_universe = read_universe_input(Path(args.universe_file))
        except (OSError, ValueError) as exc:
            print(f"ERROR: could not read universe file: {exc}", file=sys.stderr)
            return 2
    elif interactive and input("Customize the stock universe? [y/N]: ").strip().lower() == "y":
        requested_universe = [
            Security(ticker, "", "")
            for ticker in parse_tickers(input("Enter comma-separated tickers: "))
        ]

    securities = list(current.universe)
    universe_path = str(current.raw["universe"]["path"])
    universe_name = str(current.raw["universe"]["name"])
    if use_default_universe:
        defaults = load_settings(root, root / "config" / "preferences.toml")
        securities = list(defaults.universe)
        universe_path = str(defaults.raw["universe"]["path"])
        universe_name = str(defaults.raw["universe"]["name"])
    elif requested_universe is not None:
        if not requested_universe:
            print("ERROR: custom universe is empty", file=sys.stderr)
            return 2
        invalid_tickers = [
            security.ticker
            for security in requested_universe
            if not TICKER_PATTERN.fullmatch(security.ticker)
        ]
        if invalid_tickers:
            print(
                "ERROR: invalid ticker format: " + ", ".join(invalid_tickers),
                file=sys.stderr,
            )
            return 2
        print(f"Validating metadata for {len(requested_universe)} requested ticker(s)...")
        securities, enrichment_warnings = enrich_universe(requested_universe)
        for warning in enrichment_warnings:
            print(f"WARNING: {warning}")
        universe_path = "config/universe.local.csv"
        universe_name = universe_identifier(securities)

    scoring = copy.deepcopy(current.raw["scoring"])
    model_version = model_identifier(profile, scoring, weights)
    candidate_raw = copy.deepcopy(current.raw)
    candidate_raw["app"].update(
        {
            "top_candidate_limit": candidate_limit,
            "minimum_candidate_score": minimum_score,
            "minimum_overall_coverage": minimum_coverage,
        }
    )
    candidate_raw["preferences"] = {
        "profile": profile,
        "investment_horizon": horizon,
        "risk_tolerance": risk,
    }
    candidate_raw["universe"].update({"name": universe_name, "path": universe_path})
    candidate_raw["scoring"]["model_version"] = model_version
    candidate_raw["scoring"]["overall"] = weights
    candidate = Settings(root=root, raw=candidate_raw, universe=tuple(securities))
    errors, warnings = validate_settings(candidate)
    print("\nProposed personal configuration")
    print(f"  Profile: {profile} | horizon: {horizon} | risk: {risk}")
    print(f"  Model: {model_version}")
    print(f"  Universe: {universe_name} ({len(securities)} stocks)")
    print("  Weights: " + ", ".join(f"{key}={value:.1%}" for key, value in weights.items()))
    print(
        f"  Candidates: top {candidate_limit}, score >= {minimum_score:g}, "
        f"coverage >= {minimum_coverage:.0%}"
    )
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print("No files were changed.")
        return 2
    if interactive and input("Save this configuration? [y/N]: ").strip().lower() != "y":
        print("Cancelled; no files were changed.")
        return 0
    try:
        path, _backups = save_local_customization(
            root,
            securities=(
                securities
                if requested_universe is not None and not use_default_universe
                else None
            ),
            profile=profile,
            horizon=horizon,
            risk=risk,
            weights=weights,
            model_version=model_version,
            universe_name=universe_name,
            universe_path=universe_path,
            candidate_limit=candidate_limit,
            minimum_score=minimum_score,
            minimum_coverage=minimum_coverage,
        )
    except PersonalizationUpdateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Saved personal settings: {path}")
    print("Run `stockrank config-check --live` before the first report for this universe.")
    return command_config_check(argparse.Namespace(live=False))


def _command_run_analysis(args: argparse.Namespace) -> int:
    """Run and present one analysis without performing post-run validation."""
    settings = load_settings()
    run_id, report_path, warnings = run_analysis(settings, demo=args.demo, force=args.force)
    print(f"Run: {run_id}")
    print(f"Report: {report_path}")
    print(f"Warnings: {len(warnings)}")
    run = Storage(settings.database_path).latest_run()
    return int(not run or run["run_id"] != run_id or run["status"] != "completed")


def command_run(args: argparse.Namespace) -> int:
    analysis_result = _command_run_analysis(args)
    validation_result = command_validate(argparse.Namespace())
    return analysis_result or validation_result


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
    run_config = json.loads(run["config_json"])
    runtime_metadata = run_config.get("runtime", {})
    if not isinstance(runtime_metadata, dict):
        runtime_metadata = {}
    freshness_value = runtime_metadata.get("data_freshness", {})
    freshness = freshness_value if isinstance(freshness_value, dict) else {}
    scoring_quality_value = runtime_metadata.get("scoring_quality", {})
    scoring_quality = scoring_quality_value if isinstance(scoring_quality_value, dict) else {}
    print(
        f"Latest run {run['run_id']} | status={run['status']} | as_of={run['as_of']} | "
        f"provider={run['provider']} | model={run['model_version']}"
    )
    print(
        f"Universe={len(results)} | priced={priced} | eligible={eligible} | "
        f"below_coverage_threshold={sparse} | warnings={len(warnings)}"
    )
    if scoring_quality:
        weak_value = scoring_quality.get("metrics_below_minimum", [])
        weak = (
            [value for value in weak_value if isinstance(value, str)]
            if isinstance(weak_value, list)
            else []
        )
        peer_counts_value = scoring_quality.get("metric_peer_counts", {})
        peer_counts = (
            {
                metric: count
                for metric, count in peer_counts_value.items()
                if isinstance(metric, str)
                and isinstance(count, (int, float))
                and not isinstance(count, bool)
            }
            if isinstance(peer_counts_value, dict)
            else {}
        )
        lowest_samples = sorted(peer_counts.items(), key=lambda item: (item[1], item[0]))[:5]
        print(
            "Metric peer minimum="
            f"{scoring_quality.get('minimum_metric_peer_count', 'unknown')} | "
            f"below_minimum={','.join(weak) if weak else 'none'}"
        )
        print(
            "Lowest metric peer samples="
            + (
                ",".join(f"{metric}:{count}" for metric, count in lowest_samples)
                if lowest_samples
                else "unavailable"
            )
        )
    if freshness:
        fundamental_values = freshness.get("fundamentals", {})
        if not isinstance(fundamental_values, dict):
            fundamental_values = {}
        fundamental_states = Counter(
            value.get("status", "unknown") if isinstance(value, dict) else "unknown"
            for value in fundamental_values.values()
        )
        fundamental_summary = (
            ",".join(
                f"{key}:{value}" for key, value in sorted(fundamental_states.items())
            )
            if fundamental_states
            else "unavailable"
        )
        print(
            f"Price refresh={freshness.get('price_refresh_status', 'unknown')} | "
            f"fundamentals={fundamental_summary}"
        )
    elif scoring_quality:
        print("Data freshness metadata=unavailable for this stored run")
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
    try:
        settings = load_settings()
    except (OSError, KeyError, ValueError) as exc:
        print(f"Cleanup refused: invalid configuration | {exc}", file=sys.stderr)
        return 1
    errors, _ = validate_settings(settings)
    if errors:
        for error in errors:
            print(f"Cleanup refused: {error}", file=sys.stderr)
        return 1
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
        missing = [
            security.ticker for security in settings.universe if security.ticker not in matched
        ]
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


def _format_sec_document_counts(documents_checked: int, cache_hits: int) -> str:
    return (
        f"SEC documents checked={documents_checked} | cache hits={cache_hits} | "
        f"network downloads={documents_checked - cache_hits}"
    )


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
    documents_checked = 0
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
        documents_checked += sum(snapshot.documents_checked for snapshot in ticker_snapshots)
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
            cache_hit=bool(documents_checked and cache_hits == documents_checked),
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
    print(_format_sec_document_counts(documents_checked, cache_hits))
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
    print(f"Latest sync: {status} | checked={health.checked_at.isoformat()} | {health.detail}")
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
    checked_at = datetime.now(UTC)
    since_date = _years_ago(checked_at, years).date()
    try:
        refresh_policy = CompanyFactsRefreshPolicy(
            full_refresh_hours=float(sec_config.get("companyfacts_full_refresh_hours", 168.0)),
            recent_filing_window_hours=float(
                sec_config.get("companyfacts_recent_filing_window_hours", 48.0)
            ),
            recent_filing_retry_hours=float(
                sec_config.get("companyfacts_recent_filing_retry_hours", 6.0)
            ),
        )
    except (TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
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
    failures: list[str] = []
    stale_tickers: list[str] = []
    synced = 0
    stored_count = 0
    effective_count = 0
    full_core_coverage = 0
    concept_names = core_concepts
    cache_hits = 0
    documents_checked = 0
    refreshed_companies = 0
    reused_companies = 0
    refresh_reasons: Counter[str] = Counter()
    local_processing_ms = 0.0
    fetch_processing_ms = 0.0
    database_write_ms = 0.0
    unmatched_accessions = 0
    endpoint = "https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json"
    try:
        client = SecClient.from_settings(settings)
        directory = SecIdentityDirectory.from_settings(settings, client)
        identity_snapshot = directory.fetch(force=bool(args.force))
        identities = directory.index_by_ticker(identity_snapshot.identities)
        companyfacts = SecCompanyFacts.from_settings(settings, client)
        config_fingerprint = companyfacts_config_fingerprint(
            history_years=years,
            forms=companyfacts.forms,
            concepts=companyfacts.concept_specs,
        )
        concept_names = tuple(spec.canonical_name for spec in companyfacts.concept_specs)
        unknown_core = sorted(set(core_concepts) - set(concept_names))
        if unknown_core:
            raise SecError(
                "SEC Company Facts core concepts are not configured: " + ", ".join(unknown_core)
            )
        entity_overrides = load_sec_entity_overrides(settings)
    except SecError as exc:
        failures.append(f"Company Facts setup: {exc}")
        identities = {}
        companyfacts = None
        config_fingerprint = ""
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
        local_started = time.perf_counter()
        filings = tuple(storage.get_sec_filings(ticker, since_date=since_date))
        if not filings:
            failures.append(f"{ticker}: no stored SEC filings; run sec-filings-sync first")
            continue
        stored_facts = tuple(storage.get_sec_company_facts(ticker, since_date=since_date))
        state = storage.get_sec_companyfacts_refresh_state(ticker)
        ciks = [value.cik for value in sync_identities]
        current_identity_fingerprint = identity_fingerprint(ciks)
        current_filing_fingerprint = filing_fingerprint(filings)
        current_latest_filing_at = latest_filing_at(filings)
        decision = decide_companyfacts_refresh(
            now=checked_at,
            force=bool(args.force),
            has_local_facts=bool(stored_facts),
            state=state,
            current_identity_fingerprint=current_identity_fingerprint,
            current_filing_fingerprint=current_filing_fingerprint,
            current_config_fingerprint=config_fingerprint,
            current_latest_filing_at=current_latest_filing_at,
            policy=refresh_policy,
        )
        local_processing_ms += (time.perf_counter() - local_started) * 1000
        refresh_reasons[decision.reason] += 1
        facts = stored_facts
        ticker_unmatched_accessions = state.unmatched_accessions if state else 0
        snapshots = []
        if decision.refresh:
            ticker_facts = {}
            try:
                assert companyfacts is not None
                fetch_started = time.perf_counter()
                for sync_identity in sync_identities:
                    snapshot = companyfacts.fetch(
                        sync_identity,
                        ticker=ticker,
                        since_date=since_date,
                        filings=filings,
                        force=decision.bypass_raw_cache,
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
                fetch_processing_ms += (time.perf_counter() - fetch_started) * 1000
                write_started = time.perf_counter()
                storage.replace_sec_company_facts(
                    ticker=ticker,
                    ciks=ciks,
                    since_date=since_date,
                    facts=ticker_facts.values(),
                )
                facts = tuple(ticker_facts.values())
                ticker_unmatched_accessions = sum(
                    snapshot.unmatched_accessions for snapshot in snapshots
                )
                if snapshots and not any(snapshot.stale for snapshot in snapshots):
                    storage.save_sec_companyfacts_refresh_state(
                        SecCompanyFactsRefreshState(
                            ticker=ticker,
                            identity_fingerprint=current_identity_fingerprint,
                            filing_fingerprint=current_filing_fingerprint,
                            config_fingerprint=config_fingerprint,
                            last_successful_refresh_at=min(
                                snapshot.fetched_at for snapshot in snapshots
                            ),
                            latest_filing_at=current_latest_filing_at,
                            unmatched_accessions=ticker_unmatched_accessions,
                            last_refresh_reason=decision.reason,
                        )
                    )
                database_write_ms += (time.perf_counter() - write_started) * 1000
            except SecError as exc:
                failures.append(f"{ticker}: {exc}")
                continue
            refreshed_companies += 1
            cache_hits += sum(snapshot.cache_hit for snapshot in snapshots)
            documents_checked += len(snapshots)
            if any(snapshot.stale for snapshot in snapshots):
                stale_tickers.append(ticker)
        else:
            reused_companies += 1
        synced += 1
        stored_count += len(facts)
        assert companyfacts is not None
        effective = companyfacts.effective_facts(facts)
        effective_count += len(effective)
        present = {fact.canonical_name for fact in effective}
        for concept in concept_names:
            concept_coverage[concept] += concept in present
        full_core_coverage += all(concept in present for concept in core_concepts)
        unmatched_accessions += ticker_unmatched_accessions

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
        f"refreshed={refreshed_companies}",
        f"reused={reused_companies}",
        f"network_downloads={documents_checked - cache_hits}",
    ]
    details.extend(
        f"{concept}={coverage}/{len(selected)}" for concept, coverage in concept_coverage.items()
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
            cache_hit=bool(
                reused_companies == len(selected)
                or (documents_checked and cache_hits == documents_checked)
            ),
            detail="; ".join(details),
        )
    )
    print(
        f"SEC Company Facts: {status if synced else 'unavailable'} | "
        f"companies={synced}/{len(selected)} | facts={stored_count} | "
        f"effective={effective_count} | core={full_core_coverage}/{len(selected)} | "
        f"since={since_date.isoformat()} | latency={latency_ms:.0f}ms"
    )
    print(f"Refresh decisions: refreshed={refreshed_companies} | reused locally={reused_companies}")
    print(_format_sec_document_counts(documents_checked, cache_hits))
    print(
        f"Timing: local decisions/reads={local_processing_ms:.0f}ms | "
        f"SEC fetch/parse={fetch_processing_ms:.0f}ms | "
        f"database writes={database_write_ms:.0f}ms"
    )
    print("Refresh reasons:")
    for reason, count in sorted(refresh_reasons.items()):
        print(f"  {reason}: {count}")
    print("Metric coverage:")
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
        str(value) for value in settings.raw.get("sec", {}).get("companyfacts_core_concepts", ())
    )
    concept_names = tuple(spec.canonical_name for spec in load_sec_concept_specs(settings))
    concept_coverage = {concept: 0 for concept in concept_names}
    fact_count = 0
    complete = 0
    for ticker in tickers:
        facts = SecCompanyFacts.effective_facts(tuple(storage.get_sec_company_facts(ticker)))
        fact_count += len(facts)
        present = {fact.canonical_name for fact in facts}
        for concept in concept_names:
            concept_coverage[concept] += concept in present
        complete += all(concept in present for concept in core_concepts)
    print(f"SEC Company Facts effective={fact_count} | core coverage={complete}/{len(tickers)}")
    print("Concept coverage:")
    for key, value in concept_coverage.items():
        print(f"  {key}: {value}/{len(tickers)}")
    status = "healthy" if health.status == "healthy" and complete == len(tickers) else "partial"
    print(f"Latest sync: {status} | checked={health.checked_at.isoformat()} | {health.detail}")
    return 0 if status == "healthy" else 1


def _financial_as_of(value: str | None, timezone_name: str) -> datetime:
    if not value:
        return datetime.now(UTC)
    timezone = ZoneInfo(timezone_name)
    if len(value) == 10:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("--as-of must be an ISO date or datetime") from exc
        return datetime.combine(parsed_date, datetime_time.max, timezone).astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("--as-of must be an ISO date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(UTC)


def _financial_metric_lookup(
    snapshot: SecFinancialSnapshot,
) -> dict[tuple[str, str], SecFinancialMetric]:
    return {(metric.metric_name, metric.period_kind): metric for metric in snapshot.metrics}


def command_sec_financials_build(args: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    try:
        as_of = _financial_as_of(args.as_of, str(settings.raw["app"]["timezone"]))
    except (ValueError, ZoneInfoNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
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
    calculator = SecFinancialCalculator()
    started = time.perf_counter()
    failures: list[str] = []
    snapshots = []
    for security in selected:
        ticker = normalize_sec_ticker(security.ticker)
        facts = tuple(storage.get_sec_company_facts(ticker))
        if not facts:
            failures.append(f"{ticker}: no stored SEC Company Facts")
            continue
        try:
            snapshot = calculator.build_snapshot(
                ticker=ticker,
                company_name=facts[0].company_name or security.company,
                sector=security.sector,
                facts=facts,
                as_of=as_of,
            )
            storage.save_sec_financial_snapshot(snapshot)
        except (ValueError, ArithmeticError) as exc:
            failures.append(f"{ticker}: {exc}")
            continue
        snapshots.append(snapshot)

    coverage_keys = (
        ("revenue", "annual"),
        ("revenue", "quarter"),
        ("revenue", "ttm"),
        ("net_income", "ttm"),
        ("free_cash_flow", "ttm"),
        ("revenue_growth", "annual"),
        ("earnings_growth", "annual"),
        ("gross_margin", "ttm"),
        ("net_margin", "ttm"),
        ("return_on_equity", "ttm"),
        ("current_ratio", "instant"),
    )
    coverage = {key: 0 for key in coverage_keys}
    exclusions = {key: 0 for key in coverage_keys}
    for snapshot in snapshots:
        metrics = _financial_metric_lookup(snapshot)
        for key in coverage_keys:
            metric = metrics[key]
            coverage[key] += metric.value is not None
            exclusions[key] += metric.quality == "excluded"
    full_scope = len(selected) == len(settings.universe)
    status = "healthy" if len(snapshots) == len(selected) else "degraded"
    health_status = status if full_scope else "partial"
    latency_ms = (time.perf_counter() - started) * 1000
    coverage_detail = ",".join(
        f"{name}.{period}={coverage[(name, period)]}/{len(selected)}"
        for name, period in coverage_keys
    )
    details = (
        f"snapshots={len(snapshots)}/{len(selected)}; as_of={as_of.isoformat()}; "
        f"formula={FORMULA_VERSION}; {coverage_detail}; failures={len(failures)}; "
        f"scope={len(selected)}/{len(settings.universe)}"
    )
    storage.record_provider_health(
        ProviderHealth(
            provider="sec-financials",
            checked_at=datetime.now(UTC),
            status=health_status if snapshots else "unavailable",
            endpoint=f"local://{FORMULA_VERSION}",
            latency_ms=latency_ms,
            cache_hit=True,
            detail=details,
        )
    )
    print(
        f"SEC financial snapshots: {status if snapshots else 'unavailable'} | "
        f"built={len(snapshots)}/{len(selected)} | as_of={as_of.isoformat()} | "
        f"formula={FORMULA_VERSION} | latency={latency_ms:.0f}ms"
    )
    print("Metric coverage (excluded sector rows shown separately):")
    for key in coverage_keys:
        print(f"  {key[0]}.{key[1]}: {coverage[key]}/{len(selected)} (excluded={exclusions[key]})")
    for failure in failures[:10]:
        print(f"WARNING: {failure}")
    if len(failures) > 10:
        print(f"WARNING: {len(failures) - 10} additional failures were recorded")
    print(
        f"Ranking isolation: {settings.model_version} production scores were not read or changed."
    )
    return 0 if status == "healthy" else 1


def command_sec_financials_status(_: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    health = storage.get_provider_health("sec-financials")
    tickers = [normalize_sec_ticker(security.ticker) for security in settings.universe]
    snapshots = [
        snapshot
        for ticker in tickers
        if (snapshot := storage.latest_sec_financial_snapshot(ticker)) is not None
    ]
    if not snapshots:
        print("No SEC financial snapshots exist. Run stockrank sec-financials-build.")
        return 1
    complete = sum(snapshot.status == "complete" for snapshot in snapshots)
    manifested = sum(snapshot.formula_manifest is not None for snapshot in snapshots)
    print(
        f"SEC financial snapshots={len(snapshots)}/{len(tickers)} | "
        f"usable={complete}/{len(tickers)} | formula={FORMULA_VERSION} | "
        f"formula_manifests={manifested}/{len(snapshots)}"
    )
    if manifested < len(snapshots):
        print(
            "Historical note: snapshots without formula manifests remain readable "
            "but are legacy-limited."
        )
    if health:
        print(
            f"Latest build: {health.status} | checked={health.checked_at.isoformat()} | "
            f"{health.detail}"
        )
    print("Ranking isolation: these calculations are not production ranking inputs.")
    return 0 if len(snapshots) == len(tickers) and complete == len(tickers) else 1


def command_provider_shadow_run(args: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    try:
        config = load_provider_comparison_config(settings)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
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
    comparison_run_id = uuid4().hex
    started_at = datetime.now(UTC)
    as_of = started_at
    timezone_name = str(settings.raw["app"]["timezone"])
    analysis_date = as_of.astimezone(ZoneInfo(timezone_name)).date()
    comparisons = []
    failures: list[str] = []
    for security in selected:
        ticker = normalize_sec_ticker(security.ticker)
        sec_snapshot = storage.latest_sec_financial_snapshot(ticker, available_at=as_of)
        yahoo_fundamental = storage.get_fundamental(
            ticker, settings.provider_name, fresh_only=False
        )
        try:
            comparisons.extend(
                compare_provider_metrics(
                    comparison_run_id=comparison_run_id,
                    ticker=ticker,
                    sector=security.sector,
                    as_of=as_of,
                    config=config,
                    sec_snapshot=sec_snapshot,
                    yahoo_fundamental=yahoo_fundamental,
                )
            )
        except ValueError as exc:
            failures.append(f"{ticker}: {exc}")
    expected_rows = len(selected) * len(config.metrics)
    status = "complete" if len(comparisons) == expected_rows and not failures else "failed"
    full_universe = len(selected) == len(settings.universe)
    analysis_run_id = None
    evidence_date = None
    evidence_qualified = False
    evidence_reason = "Partial-universe comparisons do not qualify as promotion evidence"
    if full_universe:
        analysis = storage.latest_run()
        if not analysis:
            evidence_reason = "No production analysis run exists"
        elif analysis["status"] != "completed":
            evidence_reason = (
                f"Latest production analysis run is {analysis['status']}, not completed"
            )
        elif analysis["provider"] != settings.provider_name:
            evidence_reason = (
                f"Latest analysis provider is {analysis['provider']}, not {settings.provider_name}"
            )
        elif analysis["universe_name"] != str(settings.raw["universe"]["name"]):
            evidence_reason = "Latest analysis used a different universe version"
        elif not analysis["completed_at"]:
            evidence_reason = "Latest production analysis has no completion time"
        elif any(
            warning.startswith("Price refresh failed")
            for warning in json.loads(analysis["warnings_json"])
        ):
            evidence_reason = "Linked production run used cached prices after a refresh failure"
        else:
            analysis_completed_at = datetime.fromisoformat(analysis["completed_at"])
            analysis_age = as_of - analysis_completed_at.astimezone(UTC)
            if analysis_age < timedelta(0):
                evidence_reason = "Latest production analysis completed after this comparison"
            elif analysis_age > timedelta(hours=PROVIDER_EVIDENCE_MAX_LINK_AGE_HOURS):
                evidence_reason = (
                    "Latest production analysis is too old to link safely "
                    f"(>{PROVIDER_EVIDENCE_MAX_LINK_AGE_HOURS} hours)"
                )
            else:
                analysis_results = storage.get_results(analysis["run_id"])
                expected_tickers = set(universe_by_ticker)
                actual_tickers = {
                    normalize_sec_ticker(result["ticker"]) for result in analysis_results
                }
                price_dates = {
                    result["price_as_of"]
                    for result in analysis_results
                    if result["price_as_of"] is not None
                }
                if actual_tickers != expected_tickers:
                    evidence_reason = "Linked production run does not contain the exact universe"
                elif any(result["price_as_of"] is None for result in analysis_results):
                    evidence_reason = "Linked production run has missing price dates"
                elif len(price_dates) != 1:
                    evidence_reason = "Linked production run has mixed market-data dates"
                elif next(iter(price_dates)) != analysis["as_of"]:
                    evidence_reason = "Production run as-of date does not match its price data"
                else:
                    analysis_run_id = analysis["run_id"]
                    evidence_date = date.fromisoformat(next(iter(price_dates)))
                    stale_rows = sum(value.classification == "stale" for value in comparisons)
                    evidence_qualified = status == "complete" and stale_rows == 0
                    evidence_reason = (
                        "Qualified: complete full-universe comparison linked to a "
                        "consistent production market-data date"
                        if evidence_qualified
                        else f"Comparison contains {stale_rows} stale provider rows"
                        if stale_rows
                        else "Comparison rows are incomplete"
                    )
    run = ProviderComparisonRun(
        comparison_run_id=comparison_run_id,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        as_of=as_of,
        config_version=config.version,
        universe_name=str(settings.raw["universe"]["name"]),
        scope_count=len(selected),
        universe_size=len(settings.universe),
        full_universe=full_universe,
        status=status,
        warnings=tuple(failures),
        analysis_run_id=analysis_run_id,
        evidence_date=evidence_date,
        evidence_qualified=evidence_qualified,
        evidence_reason=evidence_reason,
    )
    storage.save_provider_comparison_run(run, comparisons)
    classifications = Counter(value.classification for value in comparisons)
    full_dates = storage.provider_comparison_full_universe_dates(
        config.version,
        timezone_name,
        universe_name=str(settings.raw["universe"]["name"]),
    )
    detail = "; ".join(
        [
            f"run={comparison_run_id}",
            f"scope={len(selected)}/{len(settings.universe)}",
            f"rows={len(comparisons)}/{expected_rows}",
            f"full_dates={full_dates}/{config.required_full_universe_dates}",
            f"evidence_date={evidence_date.isoformat() if evidence_date else 'none'}",
            f"evidence_qualified={str(evidence_qualified).lower()}",
            *(f"{key}={value}" for key, value in sorted(classifications.items())),
        ]
    )
    storage.record_provider_health(
        ProviderHealth(
            provider="provider-shadow",
            checked_at=run.completed_at,
            status=(
                "healthy"
                if status == "complete" and full_universe and evidence_qualified
                else "partial"
                if status == "complete"
                else "degraded"
            ),
            endpoint=f"local://{config.version}",
            latency_ms=(run.completed_at - run.started_at).total_seconds() * 1000,
            cache_hit=True,
            detail=detail,
        )
    )
    print(
        f"Provider shadow run: {status} | id={comparison_run_id} | "
        f"scope={len(selected)}/{len(settings.universe)} | rows={len(comparisons)}/{expected_rows}"
    )
    print(f"Config: {config.version} | command date: {analysis_date.isoformat()}")
    print(
        "Promotion evidence: "
        + (
            f"market-data date {evidence_date.isoformat()} | production run {analysis_run_id}"
            if evidence_qualified and evidence_date
            else f"not qualified | {evidence_reason}"
        )
    )
    print("Classifications:")
    for classification, count in sorted(classifications.items()):
        print(f"  {classification}: {count}")
    print("By metric:")
    for metric_name in sorted({value.metric_name for value in comparisons}):
        metric_counts = Counter(
            value.classification for value in comparisons if value.metric_name == metric_name
        )
        detail = ", ".join(
            f"{classification}={count}" for classification, count in sorted(metric_counts.items())
        )
        print(f"  {metric_name}: {detail}")
    fallback_counts = Counter(
        value.fallback_candidate for value in comparisons if value.fallback_candidate
    )
    if fallback_counts:
        print("Fallback candidates for later review:")
        for fallback, count in sorted(fallback_counts.items()):
            print(f"  {fallback}: {count}")
    print(
        f"Promotion evidence: {full_dates}/{config.required_full_universe_dates} "
        "successful full-universe market-data dates"
    )
    material = [value for value in comparisons if value.classification == "materially_different"]
    if material:
        print("Material discrepancies:")
        for value in material[:15]:
            print(
                f"  {value.ticker} {value.metric_name}: SEC={value.sec_value} "
                f"Yahoo={value.yahoo_value} relative_diff={value.relative_difference}"
            )
        if len(material) > 15:
            print(f"  {len(material) - 15} additional material discrepancies are stored")
    for failure in failures:
        print(f"WARNING: {failure}")
    print(
        "Ranking isolation: run_results and production model "
        f"{settings.model_version} were not changed."
    )
    return 0 if status == "complete" and (not full_universe or evidence_qualified) else 1


def command_provider_shadow_status(_: argparse.Namespace) -> int:
    settings = load_settings()
    storage = Storage(settings.database_path)
    storage.initialize()
    try:
        config = load_provider_comparison_config(settings)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    run = storage.latest_provider_comparison_run(
        config_version=config.version,
        universe_name=str(settings.raw["universe"]["name"]),
    )
    if not run:
        print("No provider shadow run exists. Run stockrank provider-shadow-run.")
        return 1
    comparisons = storage.get_provider_metric_comparisons(run.comparison_run_id)
    classifications = Counter(value.classification for value in comparisons)
    full_dates = storage.provider_comparison_full_universe_dates(
        config.version,
        str(settings.raw["app"]["timezone"]),
        universe_name=str(settings.raw["universe"]["name"]),
    )
    print(
        f"Latest provider shadow run={run.comparison_run_id} | status={run.status} | "
        f"as_of={run.as_of.isoformat()} | scope={run.scope_count}/{run.universe_size}"
    )
    print(
        f"Evidence date={run.evidence_date.isoformat() if run.evidence_date else 'none'} | "
        f"qualified={run.evidence_qualified} | {run.evidence_reason}"
    )
    for classification, count in sorted(classifications.items()):
        print(f"  {classification}: {count}")
    print("By metric:")
    for metric_name in sorted({value.metric_name for value in comparisons}):
        metric_counts = Counter(
            value.classification for value in comparisons if value.metric_name == metric_name
        )
        detail = ", ".join(
            f"{classification}={count}" for classification, count in sorted(metric_counts.items())
        )
        print(f"  {metric_name}: {detail}")
    print("By sector:")
    for sector in sorted({value.sector for value in comparisons}):
        sector_counts = Counter(
            value.classification for value in comparisons if value.sector == sector
        )
        detail = ", ".join(
            f"{classification}={count}" for classification, count in sorted(sector_counts.items())
        )
        print(f"  {sector}: {detail}")
    print(
        f"Promotion evidence: {full_dates}/{config.required_full_universe_dates} "
        "successful full-universe market-data dates"
    )
    print("Ranking isolation: provider shadow rows are not production ranking inputs.")
    return 0 if run.status == "complete" else 1


def command_daily_report(args: argparse.Namespace) -> int:
    """Run every deterministic daily step; qualitative research remains a handoff."""
    force = bool(args.force)
    steps = (
        ("Configuration validation", command_config_check, argparse.Namespace(live=False)),
        ("SEC identity health", command_sec_health, argparse.Namespace(force=force)),
        (
            "SEC filing sync",
            command_sec_filings_sync,
            argparse.Namespace(force=force, years=None, ticker=None),
        ),
        (
            "SEC Company Facts sync",
            command_sec_facts_sync,
            argparse.Namespace(force=force, years=None, ticker=None),
        ),
        (
            "SEC financial snapshot build",
            command_sec_financials_build,
            argparse.Namespace(as_of=None, ticker=None),
        ),
        (
            "Yahoo ranking and base report",
            _command_run_analysis,
            argparse.Namespace(demo=False, force=force),
        ),
        (
            "SEC/Yahoo shadow comparison",
            command_provider_shadow_run,
            argparse.Namespace(ticker=None),
        ),
        ("Final validation", command_validate, argparse.Namespace()),
    )
    return run_daily_workflow(steps, load_runtime_settings=load_settings)


def command_dashboard(_: argparse.Namespace) -> int:
    dashboard_path = Path(__file__).with_name("dashboard.py")
    return launch_dashboard(
        dashboard_path,
        platform_name=sys.platform,
        executable=sys.executable,
    )


def command_morning(args: argparse.Namespace) -> int:
    """Run the deterministic daily report, then open its dashboard."""
    print("Morning workflow: building today's report before opening the dashboard.")
    report_result = command_daily_report(argparse.Namespace(force=bool(args.force)))
    if report_result:
        print(
            "Morning workflow stopped because the daily report requires attention; "
            "the dashboard was not started.",
            file=sys.stderr,
        )
        return report_result
    print("\nDaily report complete. Launching the dashboard.")
    return command_dashboard(argparse.Namespace())


def build_parser() -> argparse.ArgumentParser:
    return build_command_parser(
        {
            "configure": command_configure,
            "config-check": command_config_check,
            "setup-check": command_setup_check,
            "daily-report": command_daily_report,
            "morning": command_morning,
            "run": command_run,
            "validate-latest": command_validate,
            "research-import": command_research_import,
            "storage-status": command_storage_status,
            "storage-clean": command_storage_clean,
            "sec-health": command_sec_health,
            "sec-filings-sync": command_sec_filings_sync,
            "sec-filings-status": command_sec_filings_status,
            "sec-facts-sync": command_sec_facts_sync,
            "sec-facts-status": command_sec_facts_status,
            "sec-financials-build": command_sec_financials_build,
            "sec-financials-status": command_sec_financials_status,
            "provider-shadow-run": command_provider_shadow_run,
            "provider-shadow-status": command_provider_shadow_status,
            "dashboard": command_dashboard,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
