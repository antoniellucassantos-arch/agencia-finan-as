@echo off
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b
title Agencia Cripto - otimizar
%PY% -u -m bot.otimizar %* && %PY% -u -m bot.backtest
echo.
echo Relatorios em relatorios\otimizacao.md e relatorios\backtest.md
pause
