@echo off
REM Magpie local web frontend launcher (browser -> 127.0.0.1:8000).
REM Run one frontend at a time against the same packages.sqlite.
cd /d "%~dp0"
python -m webapp %*
if errorlevel 1 pause
