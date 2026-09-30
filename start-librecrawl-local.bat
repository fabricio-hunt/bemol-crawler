@echo off
rem Runs LibreCrawl natively on Windows (no Docker), for a single local user.
rem - Uses a 64-bit Python (Playwright has no 32-bit Windows build)
rem - Keeps the virtualenv outside the project folder so OneDrive does not sync it
rem - Binds to 127.0.0.1 only, in local mode (no login)
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_DIR=%LOCALAPPDATA%\LibreCrawl\venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "INSTALLED_REQUIREMENTS=%VENV_DIR%\requirements.installed.txt"

if exist "%VENV_PYTHON%" goto check_dependencies

echo Procurando Python 64 bits...
set "BASE_PYTHON="
call :try_python "%LOCALAPPDATA%\Python\bin\python.exe"
call :try_python "python"
call :try_python "py"
if not defined BASE_PYTHON goto no_python

echo Criando ambiente virtual em "%VENV_DIR%"...
"%BASE_PYTHON%" -m venv "%VENV_DIR%"
if errorlevel 1 goto venv_failed

:check_dependencies
fc /b "requirements.txt" "%INSTALLED_REQUIREMENTS%" >nul 2>&1
if not errorlevel 1 goto run

echo Instalando dependencias...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto install_failed
echo Instalando o Chromium para renderizacao de JavaScript...
"%VENV_PYTHON%" -m playwright install chromium
if errorlevel 1 goto install_failed
copy /y "requirements.txt" "%INSTALLED_REQUIREMENTS%" >nul

:run
if not exist data mkdir data
rem The app prints emoji; the default Windows console code page cannot encode them
set "PYTHONUTF8=1"
echo.
echo ================================================================================
echo LibreCrawl rodando em http://localhost:5000 (acessivel apenas neste computador)
echo Pressione Ctrl+C para encerrar.
echo ================================================================================
echo.
"%VENV_PYTHON%" main.py --local --host 127.0.0.1 --port 5000
exit /b %errorlevel%

:try_python
if defined BASE_PYTHON exit /b 0
"%~1" -c "import struct, sys; sys.exit(0 if struct.calcsize('P') == 8 and sys.version_info >= (3, 9) else 1)" >nul 2>&1
if not errorlevel 1 set "BASE_PYTHON=%~1"
exit /b 0

:no_python
echo.
echo ERRO: nenhum Python 64 bits (3.9 ou superior) foi encontrado.
echo Instale pelo site https://www.python.org/downloads/ escolhendo o instalador 64-bit.
echo.
pause
exit /b 1

:venv_failed
echo.
echo ERRO: nao foi possivel criar o ambiente virtual em "%VENV_DIR%".
pause
exit /b 1

:install_failed
echo.
echo ERRO: falha ao instalar as dependencias. Verifique a conexao com a internet/proxy
echo e execute este arquivo novamente.
pause
exit /b 1
