from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_repository_license_and_links_are_current():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    setup = (ROOT / "SETUP.md").read_text(encoding="utf-8")

    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 nlibby17" in license_text
    assert "Stock-Research-Assisstant" not in readme
    assert "Stock-Research-Assisstant" not in setup
    assert "https://github.com/nlibby17/Stock-Research-Assistant.git" in readme
    assert "https://github.com/nlibby17/Stock-Research-Assistant.git" in setup
    assert "[MIT License](LICENSE)" in readme


def test_readme_uses_two_verified_dashboard_images():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    image_paths = (
        "docs/images/dashboard-overview.jpg",
        "docs/images/dashboard-research-summary.jpg",
    )

    assert readme.count("docs/images/") == len(image_paths)
    for relative_path in image_paths:
        assert relative_path in readme
        image_bytes = (ROOT / relative_path).read_bytes()
        assert image_bytes.startswith(b"\xff\xd8\xff")
        assert len(image_bytes) >= 40_000


def test_ci_runs_lint_and_tests_on_all_supported_desktop_families():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "macos-latest" in workflow
    assert "ruff check ." in workflow
    assert "python -m pytest -q" in workflow


def test_agent_instructions_require_completed_research_import_workflow():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    codex = (ROOT / "CODEX.md").read_text(encoding="utf-8")
    daily = (ROOT / "docs" / "DAILY_WORKFLOW.md").read_text(encoding="utf-8")

    assert "read `CODEX.md`" in agents
    assert "research_template.json" in agents
    assert "research_template.json" in codex
    assert "stockrank research-import --file" in codex
    assert "Qualitative research=imported" in codex
    assert "separately created or previewed Markdown" in codex
    assert "read `CODEX.md`" in claude
    assert "research_template.json" in claude
    assert "Qualitative research=imported" in claude
    assert "only supported research-import artifact" in daily
    assert all(level in codex for level in ("Light", "Medium", "High", "Extra High"))
