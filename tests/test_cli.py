from argparse import Namespace
from types import SimpleNamespace

from stockrank import cli


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

    assert cli.command_setup_check(Namespace()) == 0
    assert settings.database_path.exists()


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
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.subprocess, "call", lambda command: calls.append(command) or 0)

    assert cli.command_dashboard(Namespace()) == 0
    assert calls[0][0:4] == [cli.sys.executable, "-m", "streamlit", "run"]
    assert "--server.fileWatcherType=none" in calls[0]
    assert "Press Ctrl+C in this terminal" in capsys.readouterr().out


def test_dashboard_handles_macos_control_c_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "darwin")

    def interrupt(command):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.subprocess, "call", interrupt)

    assert cli.command_dashboard(Namespace()) == 0
    output = capsys.readouterr().out
    assert "Press Control+C (⌃C) in this terminal" in output
    assert "Dashboard stopped." in output
