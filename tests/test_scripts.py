from pathlib import Path


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
    assert "pyarrow==17.0.0" in constraints
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
