@echo off
REM Launches the Label Fixer GUI. Double-click this file (or a shortcut
REM to it) to start the app. Requires uv (https://docs.astral.sh/uv/).
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo uv was not found on PATH.
    echo Install it from https://docs.astral.sh/uv/getting-started/installation/
    echo then run this file again.
    pause
    exit /b 1
)

REM pythonw = no console window while the GUI runs. "start" detaches it
REM so this cmd window can close immediately after launch.
start "" /min uv run pythonw gui.py
