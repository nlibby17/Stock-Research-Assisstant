@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
pushd "%PROJECT_ROOT%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: The Stock Research Assistant project folder could not be opened.
    echo Rerun setup from the project folder to repair the desktop shortcut.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\stockrank.exe" (
    echo ERROR: The local application environment is missing.
    echo Run this command from the project folder, then try the launcher again:
    echo powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
    echo.
    pause
    popd
    exit /b 1
)

".venv\Scripts\stockrank.exe" morning
set "STOCKRANK_EXIT=%ERRORLEVEL%"
if not "%STOCKRANK_EXIT%"=="0" (
    echo.
    echo Stock Research Assistant stopped because something requires attention.
    echo Review the message above before closing this window.
    pause
)

popd
exit /b %STOCKRANK_EXIT%
