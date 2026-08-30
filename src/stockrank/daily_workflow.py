from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol


class RuntimeSettings(Protocol):
    runtime_dir: Path


WorkflowStep = tuple[str, Callable[[argparse.Namespace], int], argparse.Namespace]


def human_elapsed(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining = divmod(seconds, 60)
    return f"{int(minutes)}m {remaining:.1f}s"


def run_daily_workflow(
    steps: Sequence[WorkflowStep],
    *,
    load_runtime_settings: Callable[[], RuntimeSettings],
) -> int:
    """Run and time the deterministic workflow assembled by the command layer."""
    workflow_started = time.perf_counter()
    failed_steps: list[str] = []
    print("Starting deterministic daily report workflow.")
    for index, (label, handler, namespace) in enumerate(steps, start=1):
        print(f"\n[{index}/{len(steps)}] {label}")
        if (
            label == "SEC/Yahoo shadow comparison"
            and "Yahoo ranking and base report" in failed_steps
        ):
            print("STEP STATUS: skipped because the production ranking step failed")
            continue
        step_started = time.perf_counter()
        result = int(handler(namespace))
        step_elapsed = human_elapsed(time.perf_counter() - step_started)
        if result:
            failed_steps.append(label)
            print(f"STEP STATUS: attention required (exit={result}) | elapsed={step_elapsed}")
            if label == "Configuration validation":
                print("Workflow stopped before provider access because configuration is invalid.")
                print(
                    "Total deterministic workflow time: "
                    f"{human_elapsed(time.perf_counter() - workflow_started)}"
                )
                return 1
        else:
            print(f"STEP STATUS: complete | elapsed={step_elapsed}")

    settings = load_runtime_settings()
    report_path = settings.runtime_dir / "reports" / "latest.md"
    template_path = settings.runtime_dir / "reports" / "research_template.json"
    print("\nDeterministic workflow finished.")
    print(f"Base report: {report_path}")
    print(f"Research template: {template_path}")
    print(
        "Qualitative current-news research is not automated by this command. "
        "A person or capable research agent must complete and import the template."
    )
    print(
        "Total deterministic workflow time: "
        f"{human_elapsed(time.perf_counter() - workflow_started)}"
    )
    if failed_steps:
        print("Steps requiring review: " + ", ".join(failed_steps))
        return 1
    print("All deterministic steps completed successfully.")
    return 0


def launch_dashboard(
    dashboard_path: Path,
    *,
    platform_name: str = sys.platform,
    executable: str = sys.executable,
    process_call: Callable[[list[str]], int] = subprocess.call,
) -> int:
    """Launch Streamlit with platform-specific shutdown guidance."""
    stop_shortcut = "Control+C (⌃C)" if platform_name == "darwin" else "Ctrl+C"
    border = "=" * 62
    print(f"\n{border}")
    print("  DASHBOARD IS RUNNING")
    print(f"  To stop it: press {stop_shortcut} in this terminal")
    print(border)
    command = [
        executable,
        "-m",
        "streamlit",
        "run",
        "--server.fileWatcherType=none",
        str(dashboard_path),
    ]
    try:
        return process_call(command)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        return 0
