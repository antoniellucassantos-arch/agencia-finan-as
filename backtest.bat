@echo off
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b
title Agencia Cripto - backtest
%PY% -u -m bot.backtest %*
echo.
echo Relatorio completo em relatorios\backtest.md
pause
