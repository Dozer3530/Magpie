@echo off
REM One-click backup of packages.sqlite -> data\backups\packages_<timestamp>.sqlite
title Magpie - Back up data
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on your PATH.
  echo Install Python 3 ^(python.org^), then try again.
  echo.
  pause
  exit /b 1
)

python -m app.services.maintenance
echo.
echo (Backups live in data\backups\. You can close this window.)
pause
