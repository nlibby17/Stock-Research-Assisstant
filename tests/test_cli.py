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
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    assert cli.command_setup_check(Namespace()) == 0
    assert settings.database_path.exists()


def test_daily_report_runs_all_steps_and_reports_degradation(monkeypatch, tmp_path, capsys):
    calls = []
    handlers = (
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
            return 1 if result == 1 else 0

        monkeypatch.setattr(cli, name, handler)

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: SimpleNamespace(runtime_dir=tmp_path / "runtime"),
    )

    assert cli.command_daily_report(Namespace(force=True)) == 1
    assert [name for name, _ in calls] == list(handlers)
    assert calls[0][1].force is True
    assert calls[4][1].demo is False
    output = capsys.readouterr().out
    assert "Steps requiring review: SEC filing sync" in output
    assert "Qualitative current-news research is not automated" in output


def test_daily_report_skips_shadow_evidence_after_ranking_failure(
    monkeypatch, tmp_path, capsys
):
    calls = []
    handlers = (
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
    daily = parser.parse_args(["daily-report", "--force"])
    assert daily.handler is cli.command_daily_report
    assert daily.force is True
