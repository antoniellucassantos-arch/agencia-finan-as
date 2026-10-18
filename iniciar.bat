@echo off
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b
title Agencia Cripto - ao vivo
echo Abrindo a Agencia Cripto (dinheiro ficticio). Deixe esta janela aberta; Ctrl+C para sair.
%PY% -u -m bot.aovivo %*
pause
