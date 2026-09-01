param(
    [string]$DesktopPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherPath = Join-Path $projectRoot "launchers\Stock Research Assistant.cmd"

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "The Windows launcher is missing: $launcherPath"
}

if (-not $DesktopPath.Trim()) {
    $DesktopPath = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::DesktopDirectory
    )
}
if (-not $DesktopPath -or -not (Test-Path -LiteralPath $DesktopPath -PathType Container)) {
    throw "The Desktop folder could not be found."
}

$shortcutPath = Join-Path $DesktopPath "Stock Research Assistant.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcherPath
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Run the Stock Research Assistant morning report and dashboard"
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Host "Desktop shortcut created: $shortcutPath"
