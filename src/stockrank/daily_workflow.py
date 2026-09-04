from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol


class RuntimeSettings(Protocol):
    runtime_dir: Path


class DashboardProcess(Protocol):
    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


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


def wait_for_dashboard(
    process: DashboardProcess,
    server_port: int,
    timeout_seconds: float = 20,
) -> bool:
    """Wait for the local dashboard socket without contacting an external service."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", server_port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def launch_dashboard(
    dashboard_path: Path,
    *,
    platform_name: str = sys.platform,
    executable: str = sys.executable,
    server_port: int = 8765,
    process_start: Callable[[list[str]], DashboardProcess] | None = None,
    browser_open: Callable[[str], bool] | None = None,
    server_wait: Callable[[DashboardProcess, int], bool] | None = None,
) -> int:
    """Launch Streamlit in the default browser with shutdown guidance."""
    process_start = process_start or subprocess.Popen
    browser_open = browser_open or webbrowser.open
    server_wait = server_wait or wait_for_dashboard
    stop_shortcut = "Control+C (⌃C)" if platform_name == "darwin" else "Ctrl+C"
    dashboard_url = f"http://localhost:{server_port}"
    border = "=" * 62
    print(f"\n{border}")
    print("       /\\    STOCK RESEARCH ASSISTANT")
    print("  /\\  /  \\   ------------------------")
    print(" /  \\/       Thank you for trying my software!")
    print()
    print("  DASHBOARD IS RUNNING")
    print("  Opening it in your default browser...")
    print(f"  If the browser does not open: {dashboard_url}")
    print(f"  To stop it: press {stop_shortcut} in this terminal")
    print(border)
    command = [
        executable,
        "-m",
        "streamlit",
        "run",
        "--server.fileWatcherType=none",
        "--server.headless=true",
        f"--server.port={server_port}",
        str(dashboard_path),
    ]
    process = process_start(command)
    try:
        if server_wait(process, server_port):
            try:
                opened = browser_open(dashboard_url)
            except (OSError, webbrowser.Error):
                opened = False
            if opened:
                print("  Dashboard opened in the default browser.")
            else:
                print("  The browser could not be opened automatically; use the URL above.")
        elif process.poll() is None:
            print("  Browser opening timed out; the dashboard may still be starting.")
        return process.wait()
    except KeyboardInterrupt:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        print("\nDashboard stopped.")
        return 0
