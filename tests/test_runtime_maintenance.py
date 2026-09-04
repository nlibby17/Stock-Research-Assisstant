import os
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from stockrank import cli
from stockrank.runtime_maintenance import (
    CleanupEntry,
    CleanupPlan,
    RuntimeFile,
    apply_cleanup_plan,
    plan_cleanup,
    scan_cleanup_files,
)

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def write_file(path, age_days=40, size=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def command_environment(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    settings = SimpleNamespace(
        runtime_dir=root,
        database_path=root / "stockrank.sqlite3",
        raw={
            "retention": {"price_history_days": 550, "report_days": 30, "temporary_file_days": 7},
            "sec": {"maximum_stale_cache_hours": 168},
        },
    )
    calls = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    class FakeStorage:
        def __init__(self, path):
            assert path == settings.database_path

        def initialize(self):
            pass

        def cleanup_database(self, days, apply=False):
            calls.append((days, apply))
            return {"old_price_bars": 2}

        def counts(self):
            return {"analysis_runs": 4}

    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "validate_settings", lambda settings: ([], []))
    monkeypatch.setattr(cli, "Storage", FakeStorage)
    return root, calls


def test_command_preview_apply_and_cutoff_contract(command_environment, capsys):
    root, calls = command_environment
    expired = [write_file(root / folder / "old.txt") for folder in ("reports", "tmp", "cache/sec")]
    protected = [
        write_file(root / "reports" / name) for name in ("latest.md", "research_template.json")
    ]
    retained = [
        write_file(root / "reports" / "equal.txt", 30),
        write_file(root / "tmp" / "equal.txt", 7),
        write_file(root / "cache/sec" / "equal.txt", 7),
        write_file(root / "reports/nested/old.txt"),
        write_file(root / "logs/old.txt"),
    ]
    assert cli.command_storage_clean(Namespace(apply=False)) == 0
    preview = capsys.readouterr().out
    assert 'Dry run database cleanup: {"old_price_bars": 2}' in preview
    assert "Expired runtime files: 3" in preview
    assert "Nothing was removed." in preview
    assert all(path.exists() for path in expired + protected + retained)
    assert cli.command_storage_clean(Namespace(apply=True)) == 0
    applied = capsys.readouterr().out
    assert "Applied database cleanup:" in applied
    assert (
        preview.split("Expired runtime files:")[1].split("Nothing")[0]
        == (applied.split("Expired runtime files:")[1])
    )
    assert all(not path.exists() for path in expired)
    assert all(path.exists() for path in protected + retained)
    assert calls == [(550, False), (550, True)]


def test_status_includes_sidecars_nested_files_and_missing_folders(command_environment, capsys):
    root, _ = command_environment
    for suffix in ("", "-wal", "-shm"):
        write_file(root / ("stockrank.sqlite3" + suffix), size=2)
    write_file(root / "reports/nested/report.md", size=4)
    assert cli.command_storage_status(Namespace()) == 0
    assert capsys.readouterr().out == (
        "database: 6.0 B\nreports: 4.0 B\nsec_cache: 0.0 B\nlogs: 0.0 B\n"
        "temporary: 0.0 B\ntotal: 10.0 B\nanalysis_runs: 4 rows\n"
    )


def make_plan(root):
    return plan_cleanup(
        root,
        scan_cleanup_files(root),
        report_cutoff=NOW - timedelta(days=30),
        temporary_cutoff=NOW - timedelta(days=7),
        sec_cache_cutoff=NOW - timedelta(days=7),
    )


@pytest.mark.parametrize("unsafe", ["outside", "nested", "protected", "duplicate", "root"])
def test_apply_refuses_entire_unsafe_plan_before_deleting_anything(tmp_path, unsafe):
    root = tmp_path / "runtime"
    old = write_file(root / "tmp/old.txt")
    plan = make_plan(root)
    target = {
        "outside": tmp_path / "outside.txt",
        "nested": root / "tmp/nested/file.txt",
        "protected": root / "reports/LATEST.MD",
        "duplicate": old,
        "root": old,
    }[unsafe]
    write_file(target)
    stat = target.stat()
    entry = CleanupEntry(RuntimeFile(target, stat.st_size, stat.st_mtime_ns), NOW)
    forged = CleanupPlan(tmp_path if unsafe == "root" else root, plan.entries + (entry,))
    with pytest.raises(ValueError):
        apply_cleanup_plan(forged, root)
    assert old.exists() and target.exists()


def test_changed_file_refuses_apply_without_removing_earlier_candidates(tmp_path):
    root = tmp_path / "runtime"
    first = write_file(root / "reports/old.md")
    changed = write_file(root / "tmp/old.txt")
    plan = make_plan(root)
    changed.write_text("new content", encoding="utf-8")
    with pytest.raises(ValueError, match="changed since planning"):
        apply_cleanup_plan(plan, root)
    assert first.exists() and changed.exists()


def test_planner_is_pure_and_rejects_naive_cutoffs(tmp_path):
    root = tmp_path / "nonexistent"
    file = RuntimeFile(root / "tmp/old.txt", 1, 0)
    kwargs = {"report_cutoff": NOW, "temporary_cutoff": NOW, "sec_cache_cutoff": NOW}
    assert plan_cleanup(root, (file,), **kwargs).entries[0].file == file
    assert not root.exists()
    kwargs["report_cutoff"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        plan_cleanup(root, (file,), **kwargs)


def test_apply_rechecks_directory_containment(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    old = write_file(root / "tmp/old.txt")
    plan = make_plan(root)
    path_type = type(old)
    original = path_type.resolve

    def redirected(path, *args, **kwargs):
        if path == old:
            return tmp_path / "outside.txt"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(path_type, "resolve", redirected)
    with pytest.raises(ValueError, match="redirected"):
        apply_cleanup_plan(plan, root)
    assert old.exists()


@pytest.mark.parametrize("directory", [False, True])
def test_scan_refuses_real_symlinks(tmp_path, directory):
    root = tmp_path / "runtime"
    external = write_file(tmp_path / "external/keep.txt")
    root.mkdir()
    link = root / "tmp" if directory else root / "tmp/link.txt"
    link.parent.mkdir(exist_ok=True)
    try:
        link.symlink_to(external.parent if directory else external, target_is_directory=directory)
    except OSError:
        pytest.skip("Creating symlinks requires permission on this Windows installation")
    with pytest.raises(ValueError, match="[Ll]inked"):
        make_plan(root)
    assert external.read_bytes() == b"xxx"


def test_command_refuses_unsafe_plan_before_database_apply(
    command_environment, monkeypatch, capsys
):
    root, calls = command_environment
    write_file(root / "tmp/old.txt")
    path_type = type(root)
    original = path_type.resolve

    def redirected(path, *args, **kwargs):
        if path == root / "tmp":
            return root.parent / "outside"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(path_type, "resolve", redirected)
    assert cli.command_storage_clean(Namespace(apply=True)) == 1
    assert calls == []
    assert "Cleanup refused" in capsys.readouterr().err


def test_apply_rechecks_each_file_after_preflight(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    first = write_file(root / "reports/old.md")
    second = write_file(root / "tmp/old.txt")
    plan = make_plan(root)
    path_type = type(first)
    unlink = path_type.unlink

    def change_during_apply(path, *args, **kwargs):
        unlink(path, *args, **kwargs)
        if path == first:
            second.write_text("new data arrived", encoding="utf-8")

    monkeypatch.setattr(path_type, "unlink", change_during_apply)
    with pytest.raises(ValueError, match="changed since planning"):
        apply_cleanup_plan(plan, root)
    assert not first.exists()
    assert second.read_text(encoding="utf-8") == "new data arrived"


def test_apply_rejects_unexpired_forged_candidate(tmp_path):
    root = tmp_path / "runtime"
    path = write_file(root / "tmp/recent.txt", age_days=0)
    stat = path.stat()
    forged = CleanupPlan(root, (CleanupEntry(RuntimeFile(path, 3, stat.st_mtime_ns), NOW),))
    with pytest.raises(ValueError, match="not expired"):
        apply_cleanup_plan(forged, root)
    assert path.exists()


def test_command_reports_partial_apply_failure(command_environment, monkeypatch, capsys):
    root, calls = command_environment
    old = write_file(root / "tmp/old.txt")

    def fail_apply(plan, root):
        raise OSError("file is locked")

    monkeypatch.setattr(cli, "apply_cleanup_plan", fail_apply)
    assert cli.command_storage_clean(Namespace(apply=True)) == 1
    output = capsys.readouterr()
    assert "Runtime file cleanup stopped: file is locked" in output.err
    assert "may already have completed" in output.err
    assert calls == [(550, True)]
    assert old.exists()
