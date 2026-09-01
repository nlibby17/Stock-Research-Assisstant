from argparse import Namespace
from types import SimpleNamespace

from stockrank import cli, daily_workflow


class FakeDashboardProcess:
    def __init__(self, *, interrupt: bool = False):
        self.interrupt = interrupt
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def poll(self):
        return None if not self.terminated else 0

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.interrupt and self.wait_calls == 1:
            raise KeyboardInterrupt
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.terminated = True


class FakeSocketConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_setup_check_initializes_runtime(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "preferences.toml").write_text("", encoding="utf-8")
    (config_dir / "universe.csv").write_text("ticker,company,sector\nA,Alpha,Test\n")
    settings = SimpleNamespace(
        root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        database_path=tmp_path / "runtime" / "stockrank.sqlite3",
        raw={"universe": {"path": "config/universe.csv"}},
        universe=(SimpleNamespace(ticker="A"),),
        sec_user_agent="Stock Research Test test@example.org",
        model_version="test-v1",
        profile_name="balanced",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "validate_settings", lambda value: ([], []))
    monkeypatch.setattr(cli, "_check_pyarrow_import", lambda: (None, "15.0.2"))

    assert cli.command_setup_check(Namespace()) == 0
    assert settings.database_path.exists()


def test_pyarrow_native_check_reports_a_child_process_crash(monkeypatch):
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=-11, stdout="", stderr=""),
    )

    failure, version = cli._check_pyarrow_import()

    assert "terminated by signal 11" in failure
    assert "setup or update helper" in failure
    assert version is None


def test_daily_report_runs_all_steps_and_reports_degradation(monkeypatch, tmp_path, capsys):
    calls = []
    handlers = (
        "command_config_check",
        "command_sec_health",
        "command_sec_filings_sync",
        "command_sec_facts_sync",
        "command_sec_financials_build",
        "command_run",
        "command_provider_shadow_run",
        "command_validate",
    )

    for index, name in enumerate(handlers):

        def handler(args, *, current=name, result=index):
            calls.append((current, args))
            return 1 if result == 2 else 0

        monkeypatch.setattr(cli, name, handler)

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: SimpleNamespace(runtime_dir=tmp_path / "runtime"),
    )

    assert cli.command_daily_report(Namespace(force=True)) == 1
    assert [name for name, _ in calls] == list(handlers)
    assert calls[1][1].force is True
    assert calls[5][1].demo is False
    output = capsys.readouterr().out
    assert "Steps requiring review: SEC filing sync" in output
    assert "Qualitative current-news research is not automated" in output
    assert "STEP STATUS: complete | elapsed=" in output
    assert "Total deterministic workflow time:" in output


def test_daily_report_skips_shadow_evidence_after_ranking_failure(monkeypatch, tmp_path, capsys):
    calls = []
    handlers = (
        "command_config_check",
        "command_sec_health",
        "command_sec_filings_sync",
        "command_sec_facts_sync",
        "command_sec_financials_build",
        "command_run",
        "command_provider_shadow_run",
        "command_validate",
    )
    for name in handlers:

        def handler(args, *, current=name):
            calls.append(current)
            return 1 if current == "command_run" else 0

        monkeypatch.setattr(cli, name, handler)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: SimpleNamespace(runtime_dir=tmp_path / "runtime"),
    )

    assert cli.command_daily_report(Namespace(force=False)) == 1
    assert "command_provider_shadow_run" not in calls
    assert "command_validate" in calls
    assert "skipped because the production ranking step failed" in capsys.readouterr().out


def test_parser_exposes_setup_and_daily_commands():
    parser = cli.build_parser()
    assert parser.parse_args(["setup-check"]).handler is cli.command_setup_check
    assert parser.parse_args(["config-check"]).handler is cli.command_config_check
    configure = parser.parse_args(["configure", "--profile", "growth", "--yes"])
    assert configure.handler is cli.command_configure
    assert configure.profile == "growth"
    daily = parser.parse_args(["daily-report", "--force"])
    assert daily.handler is cli.command_daily_report
    assert daily.force is True
    morning = parser.parse_args(["morning", "--force"])
    assert morning.handler is cli.command_morning
    assert morning.force is True


def test_morning_runs_report_before_dashboard(monkeypatch, capsys):
    calls = []

    def daily(args):
        calls.append(("daily-report", args.force))
        return 0

    def dashboard(args):
        calls.append(("dashboard", args))
        return 0

    monkeypatch.setattr(cli, "command_daily_report", daily)
    monkeypatch.setattr(cli, "command_dashboard", dashboard)

    assert cli.command_morning(Namespace(force=True)) == 0
    assert [name for name, _ in calls] == ["daily-report", "dashboard"]
    assert calls[0][1] is True
    assert "Daily report complete. Launching the dashboard." in capsys.readouterr().out


def test_morning_does_not_launch_dashboard_after_report_failure(monkeypatch, capsys):
    monkeypatch.setattr(cli, "command_daily_report", lambda args: 1)
    dashboard_calls = []
    monkeypatch.setattr(cli, "command_dashboard", lambda args: dashboard_calls.append(args) or 0)

    assert cli.command_morning(Namespace(force=False)) == 1
    assert dashboard_calls == []
    assert "dashboard was not started" in capsys.readouterr().err


def test_dashboard_disables_file_watching_and_shows_windows_stop_key(monkeypatch, capsys):
    calls = []
    browser_calls = []
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(
        daily_workflow.subprocess,
        "Popen",
        lambda command: calls.append(command) or FakeDashboardProcess(),
    )
    monkeypatch.setattr(daily_workflow, "wait_for_dashboard", lambda process, port: True)
    monkeypatch.setattr(
        daily_workflow.webbrowser,
        "open",
        lambda url: browser_calls.append(url) or True,
    )

    assert cli.command_dashboard(Namespace()) == 0
    assert calls[0][0:4] == [cli.sys.executable, "-m", "streamlit", "run"]
    assert "--server.fileWatcherType=none" in calls[0]
    assert "--server.headless=true" in calls[0]
    assert "--server.port=8765" in calls[0]
    assert browser_calls == ["http://localhost:8765"]
    output = capsys.readouterr().out
    assert "=" * 62 in output
    assert "DASHBOARD IS RUNNING" in output
    assert "Opening it in your default browser" in output
    assert "If the browser does not open: http://localhost:8765" in output
    assert "Dashboard opened in the default browser" in output
    assert "To stop it: press Ctrl+C in this terminal" in output


def test_dashboard_handles_macos_control_c_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    process = FakeDashboardProcess(interrupt=True)
    monkeypatch.setattr(daily_workflow.subprocess, "Popen", lambda command: process)
    monkeypatch.setattr(daily_workflow, "wait_for_dashboard", lambda value, port: True)
    monkeypatch.setattr(daily_workflow.webbrowser, "open", lambda url: True)

    assert cli.command_dashboard(Namespace()) == 0
    assert process.terminated is True
    assert process.killed is False
    output = capsys.readouterr().out
    assert "DASHBOARD IS RUNNING" in output
    assert "To stop it: press Control+C (⌃C) in this terminal" in output
    assert "Dashboard stopped." in output


def test_dashboard_keeps_running_when_browser_open_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        daily_workflow.subprocess,
        "Popen",
        lambda command: FakeDashboardProcess(),
    )
    monkeypatch.setattr(daily_workflow, "wait_for_dashboard", lambda process, port: True)
    monkeypatch.setattr(daily_workflow.webbrowser, "open", lambda url: False)

    assert cli.command_dashboard(Namespace()) == 0
    assert "browser could not be opened automatically" in capsys.readouterr().out


def test_dashboard_ready_wait_uses_only_the_local_port(monkeypatch):
    calls = []
    process = FakeDashboardProcess()
    monkeypatch.setattr(
        daily_workflow.socket,
        "create_connection",
        lambda address, timeout: calls.append((address, timeout)) or FakeSocketConnection(),
    )

    assert daily_workflow.wait_for_dashboard(process, 8765, timeout_seconds=1) is True
    assert calls == [(('127.0.0.1', 8765), 0.25)]


def test_dashboard_ready_wait_stops_when_process_exits(monkeypatch):
    process = FakeDashboardProcess()
    process.terminated = True
    monkeypatch.setattr(
        daily_workflow.socket,
        "create_connection",
        lambda address, timeout: (_ for _ in ()).throw(AssertionError("socket was checked")),
    )

    assert daily_workflow.wait_for_dashboard(process, 8765, timeout_seconds=1) is False
