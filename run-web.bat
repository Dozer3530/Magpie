@echo off
REM Magpie local web frontend launcher (browser -> 127.0.0.1:8000).
REM Run one frontend at a time against the same packages.sqlite.
title Magpie - Weekly Package Builder
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on your PATH.
  echo Install Python 3 ^(python.org^), then double-click this again.
  echo.
  pause
  exit /b 1
)

echo Starting Magpie... your browser will open when it's ready.
echo.
python -m webapp %*

echo.
echo Magpie has stopped. You can close this window.
pause
