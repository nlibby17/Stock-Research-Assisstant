param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found. Install Git, reopen PowerShell, and rerun this script."
}
if (-not (Test-Path -LiteralPath ".git")) {
    throw "This folder is not a Git clone. Use scripts/setup.ps1 for a new installation."
}
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    throw "The local Python environment is missing. Run scripts/setup.ps1 first."
}

$sourceChanges = @(& git status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw "Git could not inspect the working tree."
}
if ($sourceChanges.Count -gt 0) {
    Write-Host "Update stopped because source-controlled or untracked project files changed:"
    $sourceChanges | ForEach-Object { Write-Host "  $_" }
    throw "Commit, remove, or preserve those files outside the project before updating."
}

$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or -not $branch) {
    throw "Update requires a normal checked-out branch, not a detached commit."
}

$personalPaths = @(
    ".env",
    "config\preferences.local.toml",
    "config\universe.local.csv"
)
$personalHashes = @{}
foreach ($personalPath in $personalPaths) {
    if (Test-Path -LiteralPath $personalPath) {
        $personalHashes[$personalPath] = (Get-FileHash -LiteralPath $personalPath -Algorithm SHA256).Hash
    }
}

Write-Host "Updating branch '$branch' with a fast-forward-only pull..."
& git pull --ff-only origin $branch
if ($LASTEXITCODE -ne 0) {
    throw "Git update failed. No merge was created. Review the message above."
}

Write-Host "Synchronizing Python dependencies..."
& ".\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

Write-Host "Validating the installation and active personal configuration..."
& ".\.venv\Scripts\stockrank.exe" setup-check
if ($LASTEXITCODE -ne 0) {
    throw "Setup validation failed."
}
& ".\.venv\Scripts\stockrank.exe" config-check
if ($LASTEXITCODE -ne 0) {
    throw "Personal configuration validation failed."
}

if (-not $SkipTests) {
    Write-Host "Running the automated test suite..."
    $pytestTemp = Join-Path $projectRoot ("runtime\tmp\pytest-update-" + $PID)
    New-Item -ItemType Directory -Path $pytestTemp -Force | Out-Null
    & ".\.venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider --basetemp $pytestTemp
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed after the update."
    }
}

foreach ($personalPath in $personalHashes.Keys) {
    if (-not (Test-Path -LiteralPath $personalPath)) {
        throw "Personal file disappeared during update: $personalPath"
    }
    $updatedHash = (Get-FileHash -LiteralPath $personalPath -Algorithm SHA256).Hash
    if ($updatedHash -ne $personalHashes[$personalPath]) {
        throw "Personal file changed unexpectedly during update: $personalPath"
    }
}

Write-Host "Update complete. Personal settings and runtime data were preserved."
