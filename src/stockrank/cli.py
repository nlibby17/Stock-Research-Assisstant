from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stockrank.config import load_settings
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
    candidates: list[Path] = []
    for directory, cutoff, keep_names in (
        (settings.runtime_dir / "reports", report_cutoff, {"latest.md", "research_template.json"}),
        (settings.runtime_dir / "tmp", temp_cutoff, set()),
    ):
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.name not in keep_names:
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                if modified < cutoff:
                    candidates.append(path)
    print(("Applied" if apply else "Dry run") + " database cleanup: " + json.dumps(preview))
    print(f"Expired report/temp files: {len(candidates)}")
    for path in candidates:
        print(f"  {path}")
        if apply:
            path.unlink()
    if not apply:
        print(
            "Nothing was removed. Re-run with --apply to perform this exact policy-based cleanup."
        )
    return 0


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
