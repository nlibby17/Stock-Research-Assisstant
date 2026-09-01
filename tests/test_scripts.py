import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_update_script_uses_safe_git_and_preserves_personal_files():
    script = (Path.cwd() / "scripts" / "update.ps1").read_text(encoding="utf-8")

    assert "git pull --ff-only" in script
    assert "git status --porcelain" in script
    assert '".env"' in script
    assert '"config\\preferences.local.toml"' in script
    assert '"config\\universe.local.csv"' in script
    assert "Get-FileHash" in script
    assert 'stockrank.exe" setup-check' in script
    assert 'stockrank.exe" config-check' in script
    assert "--disable-pip-version-check --quiet" in script
    assert "--basetemp" in script
    assert "no:cacheprovider" in script
    assert "Remove-Item" not in script


def test_macos_setup_script_uses_local_environment_and_preserves_existing_env():
    script = (Path.cwd() / "scripts" / "setup.sh").read_text(encoding="utf-8")
    attributes = (Path.cwd() / ".gitattributes").read_text(encoding="utf-8")
    constraints = (Path.cwd() / "constraints" / "macos-11-py312.txt").read_text(
        encoding="utf-8"
    )

    assert "set -euo pipefail" in script
    assert "python_candidates=(python3.13 python3 python)" in script
    assert "python3.12" in script
    assert "macos_major < 11" in script
    assert 'macos_major" == "11"' in script
    assert "macos-11-py312.txt" in script
    assert "pyarrow==15.0.2" in constraints
    assert "17.0.0 has a confirmed native-import crash" in constraints
    assert "dependency_constraints[@]" not in script
    assert "use_macos_11_constraints=false" in script
    assert 'mv ".venv" "$backup_path"' in script
    assert 'mkdir -p ".venv-backups"' in script
    assert ".venv-backups/" in (Path.cwd() / ".gitignore").read_text(encoding="utf-8")
    assert 'pip setuptools wheel' in script
    assert "--only-binary=:all:" in script
    assert '[[ ! -f ".env" ]]' in script
    assert 'cp ".env.example" ".env"' in script
    assert '".venv/bin/stockrank" setup-check' in script
    assert "*.sh text eol=lf" in attributes
    assert "\nrm " not in script
    assert "\n    rm " not in script


def test_macos_update_script_uses_safe_git_and_preserves_personal_files():
    script = (Path.cwd() / "scripts" / "update.sh").read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert "git pull --ff-only" in script
    assert "git status --porcelain" in script
    assert 'verify_personal_file ".env"' in script
    assert 'verify_personal_file "config/preferences.local.toml"' in script
    assert 'verify_personal_file "config/universe.local.csv"' in script
    assert '".venv/bin/stockrank" setup-check' in script
    assert '".venv/bin/stockrank" config-check' in script
    assert "--disable-pip-version-check --quiet" in script
    assert "--only-binary=:all:" in script
    assert "macos-11-py312.txt" in script
    assert "dependency_constraints[@]" not in script
    assert "use_macos_11_constraints=false" in script
    assert 'environment_version" != "3.12"' in script
    assert "--basetemp" in script
    assert "no:cacheprovider" in script
    assert "git reset" not in script
    assert "\nrm " not in script
    assert "\n    rm " not in script


def test_setup_scripts_offer_explicit_desktop_launcher_choice():
    windows_setup = (Path.cwd() / "scripts" / "setup.ps1").read_text(encoding="utf-8")
    macos_setup = (Path.cwd() / "scripts" / "setup.sh").read_text(encoding="utf-8")

    assert "Create the recommended desktop shortcut? [Y/n]" in windows_setup
    assert "CreateDesktopShortcut" in windows_setup
    assert "SkipDesktopShortcut" in windows_setup
    assert "install-launcher.ps1" in windows_setup
    assert "Create the recommended desktop launcher? [Y/n]" in macos_setup
    assert "--desktop-launcher" in macos_setup
    assert "--no-desktop-launcher" in macos_setup
    assert "install-launcher.sh" in macos_setup


def test_launchers_use_project_relative_environment_and_morning_command():
    windows_launcher = (
        Path.cwd() / "launchers" / "Stock Research Assistant.cmd"
    ).read_text(encoding="utf-8")
    macos_launcher = (
        Path.cwd() / "launchers" / "Stock Research Assistant.command"
    ).read_text(encoding="utf-8")
    attributes = (Path.cwd() / ".gitattributes").read_text(encoding="utf-8")

    assert "%~dp0.." in windows_launcher
    assert '.venv\\Scripts\\stockrank.exe" morning' in windows_launcher
    assert "local application environment is missing" in windows_launcher
    assert 'dirname "${BASH_SOURCE[0]}"' in macos_launcher
    assert '"$stockrank_executable" morning' in macos_launcher
    assert "local application environment is missing" in macos_launcher
    assert "*.command text eol=lf" in attributes
    assert "*.cmd text eol=crlf" in attributes


@pytest.mark.skipif(os.name == "nt", reason="POSIX launcher execution test")
def test_macos_launcher_runs_from_outside_project_with_spaces(tmp_path):
    project = tmp_path / "Project Folder With Spaces"
    launcher_dir = project / "launchers"
    executable = project / ".venv" / "bin" / "stockrank"
    outside = tmp_path / "Outside Folder"
    result_file = tmp_path / "launcher-result.txt"
    launcher_dir.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    outside.mkdir()
    shutil.copy2(
        Path.cwd() / "launchers" / "Stock Research Assistant.command",
        launcher_dir / "Stock Research Assistant.command",
    )
    executable.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n%s\\n" "$PWD" "$1" > "$LAUNCHER_RESULT"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)

    env = os.environ.copy()
    env["LAUNCHER_RESULT"] = str(result_file)
    completed = subprocess.run(
        ["bash", str(launcher_dir / "Stock Research Assistant.command")],
        cwd=outside,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert result_file.read_text(encoding="utf-8").splitlines() == [
        str(project),
        "morning",
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX launcher installation test")
def test_macos_launcher_helper_creates_link_to_canonical_launcher(tmp_path):
    project = tmp_path / "Project Folder With Spaces"
    scripts_dir = project / "scripts"
    launcher_dir = project / "launchers"
    desktop = tmp_path / "Desktop Folder"
    scripts_dir.mkdir(parents=True)
    launcher_dir.mkdir()
    desktop.mkdir()
    helper = scripts_dir / "install-launcher.sh"
    launcher = launcher_dir / "Stock Research Assistant.command"
    shutil.copy2(Path.cwd() / "scripts" / "install-launcher.sh", helper)
    shutil.copy2(
        Path.cwd() / "launchers" / "Stock Research Assistant.command", launcher
    )

    completed = subprocess.run(
        ["bash", str(helper), "--desktop-dir", str(desktop)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    desktop_launcher = desktop / "Stock Research Assistant.command"
    assert completed.returncode == 0, completed.stderr
    assert desktop_launcher.is_symlink()
    assert desktop_launcher.resolve() == launcher.resolve()


@pytest.mark.skipif(os.name != "nt", reason="Windows shortcut installation test")
def test_windows_launcher_runs_from_outside_project_with_spaces(tmp_path):
    project = tmp_path / "Project Folder With Spaces"
    launcher_dir = project / "launchers"
    executable = project / ".venv" / "Scripts" / "stockrank.exe"
    outside = tmp_path / "Outside Folder"
    launcher_dir.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    outside.mkdir()
    launcher = launcher_dir / "Stock Research Assistant.cmd"
    shutil.copy2(Path.cwd() / "launchers" / "Stock Research Assistant.cmd", launcher)

    # tree.com gives us a harmless native executable with a relative-path argument:
    # finding project/morning proves the launcher changed into its own project.
    tree_executable = shutil.which("tree.com")
    assert tree_executable is not None
    shutil.copy2(tree_executable, executable)
    marker = project / "morning"
    marker.mkdir()

    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", str(launcher)],
        cwd=outside,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert str(marker).upper() in completed.stdout.strip().upper()


@pytest.mark.skipif(os.name != "nt", reason="Windows shortcut installation test")
def test_windows_launcher_helper_targets_canonical_launcher(tmp_path):
    project = tmp_path / "Project Folder With Spaces"
    scripts_dir = project / "scripts"
    launcher_dir = project / "launchers"
    desktop = tmp_path / "Desktop Folder"
    scripts_dir.mkdir(parents=True)
    launcher_dir.mkdir()
    desktop.mkdir()
    helper = scripts_dir / "install-launcher.ps1"
    launcher = launcher_dir / "Stock Research Assistant.cmd"
    shortcut = desktop / "Stock Research Assistant.lnk"
    shutil.copy2(Path.cwd() / "scripts" / "install-launcher.ps1", helper)
    shutil.copy2(Path.cwd() / "launchers" / "Stock Research Assistant.cmd", launcher)

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-DesktopPath",
            str(desktop),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert shortcut.is_file()
    escaped_shortcut = str(shortcut).replace("'", "''")
    inspect_shortcut = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut"
                f"('{escaped_shortcut}');"
                "Write-Output $s.TargetPath"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert inspect_shortcut.returncode == 0, inspect_shortcut.stderr
    assert Path(inspect_shortcut.stdout.strip()).resolve() == launcher.resolve()
