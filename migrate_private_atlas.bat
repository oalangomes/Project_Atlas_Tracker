@echo off
setlocal
cd /d "%~dp0"
title Project Atlas to Tracker Migration

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 migrate_private_atlas.py
) else (
  python migrate_private_atlas.py
)

echo.
pause
endlocal
