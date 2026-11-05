@echo off
setlocal
cd /d "%~dp0"
set "ATLAS_PYTHON=py -3"
if exist ".venv\Scripts\python.exe" (
  set "ATLAS_PYTHON=.venv\Scripts\python.exe"
)
echo.
echo ================================================
echo   Atlas Tracker - Replay da Comissao Tecnica
echo ================================================
echo.
echo Inicie o Atlas Tracker normalmente antes deste comando.
echo O replay e executado no processo local do Atlas.
echo.
%ATLAS_PYTHON% -m scripts.replay_commission_reports %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo O comando terminou com codigo %RC%. Leia as mensagens acima.
)
pause
exit /b %RC%
