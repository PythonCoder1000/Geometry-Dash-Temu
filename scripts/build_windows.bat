@echo off
REM scripts\build_windows.bat — one-dir build for Windows
REM
REM Usage (Developer PowerShell / cmd):
REM   scripts\build_windows.bat
REM
REM Output:
REM   dist\TrigonometrySprint\TrigonometrySprint.exe
REM
REM This script MUST run on a real Windows machine. PyInstaller cannot
REM cross-compile from macOS / Linux. Workflow options:
REM   * Run locally in a Windows VM.
REM   * Use GitHub Actions with a `windows-latest` runner.
REM
REM Before building for distribution: edit src\server_config.py with the
REM Lightsail URL so every built copy auto-connects.
setlocal enableextensions enabledelayedexpansion
pushd "%~dp0\.."

echo [build_windows] ensuring build deps...
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :err

echo [build_windows] wiping previous build\dist...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [build_windows] running pyinstaller...
python -m PyInstaller TrigonometrySprint.spec --noconfirm
if errorlevel 1 goto :err

echo [build_windows] done.
echo   binary : dist\TrigonometrySprint\TrigonometrySprint.exe
popd
exit /b 0

:err
echo [build_windows] FAILED — see messages above.
popd
exit /b 1
