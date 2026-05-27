@echo off
REM Earth Daily Package Organizer and Creator launcher.
cd /d "%~dp0"
python -m app %*
if errorlevel 1 pause
