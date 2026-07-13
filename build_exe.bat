@echo off
REM One-time build of a standalone LabelFixer.exe (bundles Python, so
REM end users don't need uv/Python installed at all). Must be run on
REM Windows -- PyInstaller builds for whatever OS it runs on.
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo uv was not found on PATH.
    echo Install it from https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

echo Building LabelFixer.exe (this can take a minute or two)...
uv run --with pyinstaller pyinstaller --onefile --windowed ^
    --name LabelFixer ^
    --icon icon.ico ^
    --add-data "icon.ico;." ^
    gui.py

if errorlevel 1 (
    echo.
    echo Build failed -- see the errors above.
    pause
    exit /b 1
)

echo.
echo Done. Your standalone app is at dist\LabelFixer.exe
echo You can copy that single file anywhere (Desktop, Start Menu, etc.)
echo and double-click it to run -- it already has the icon baked in.
pause
