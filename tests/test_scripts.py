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
