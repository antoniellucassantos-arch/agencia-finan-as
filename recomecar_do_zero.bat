@echo off
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b
echo Isso apaga as carteiras dos 3 robos e recomeca com o saldo inicial.
choice /m "Tem certeza"
if errorlevel 2 exit /b
%PY% -u -m bot.aovivo --zerar
pause
