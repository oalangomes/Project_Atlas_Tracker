@echo off
setlocal EnableExtensions
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_windows.ps1" -Mode scan
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
