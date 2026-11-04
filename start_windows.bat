@echo off
setlocal EnableExtensions
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_windows.ps1" -Mode start
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
