param(
    [string]$SecUserAgent = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($null -ne $pythonLauncher) {
    $pythonExecutable = $pythonLauncher.Source
    $pythonArgs = @("-3")
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "Python 3.11 or newer was not found. Install Python, then rerun this script."
    }
    $pythonExecutable = $pythonCommand.Source
    $pythonArgs = @()
}

$versionText = & $pythonExecutable @pythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$versionParts = $versionText.Split(".")
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 11)) {
    throw "Python 3.11 or newer is required; found $versionText."
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    & $pythonExecutable @pythonArgs -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]"

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
}

if ($SecUserAgent.Trim()) {
    $envLines = Get-Content -LiteralPath ".env"
    $replacement = "SEC_USER_AGENT=" + $SecUserAgent.Trim()
    if ($envLines | Where-Object { $_ -match '^SEC_USER_AGENT=' }) {
        $updated = $envLines | ForEach-Object {
            if ($_ -match '^SEC_USER_AGENT=') { $replacement } else { $_ }
        }
    } else {
        $updated = @($envLines) + $replacement
    }
    Set-Content -LiteralPath ".env" -Value $updated -Encoding utf8
    & ".\.venv\Scripts\stockrank.exe" setup-check
} else {
    Write-Host "Installation complete. Edit .env and replace the SEC_USER_AGENT placeholder."
    Write-Host "Then run: .\.venv\Scripts\stockrank.exe setup-check"
}
