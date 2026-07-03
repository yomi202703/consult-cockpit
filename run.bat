@echo off
rem consult-cockpit launcher (Windows) - the run.sh counterpart.
rem
rem   run.bat [REPO]     launch pointed at REPO (default: current dir)
rem   run.bat doctor     validate prerequisites and exit
rem
rem Keys: Windows has no keychain backend here - put WORKER_LLM_API_KEY in .env
rem (same precedence otherwise: explicit env var over .env value).
rem Overrides: COCKPIT_PYTHON, COCKPIT_SCRIPTS, COCKPIT_ENV, COCKPIT_PORT.
chcp 65001 >nul
set PYTHONUTF8=1
set HERE=%~dp0
if not defined COCKPIT_PORT set COCKPIT_PORT=8079
if not defined COCKPIT_SCRIPTS if exist "%HERE%scrape" set COCKPIT_SCRIPTS=%HERE%scrape

set PY=python
where py >nul 2>nul
if %errorlevel%==0 set PY=py -3
if defined COCKPIT_PYTHON set PY=%COCKPIT_PYTHON%

if "%~1"=="doctor" (
  %PY% "%HERE%src\server.py" doctor
  exit /b %errorlevel%
)
if "%~1"=="auth" (
  echo [cockpit] the keychain backend is macOS-only - on Windows put the key in .env:
  echo   WORKER_LLM_API_KEY=...
  exit /b 1
)

rem already running? just open the browser for the live instance.
%PY% -c "import socket;s=socket.socket();s.settimeout(0.5);raise SystemExit(0 if s.connect_ex(('127.0.0.1',int('%COCKPIT_PORT%')))==0 else 1)" >nul 2>nul
if %errorlevel%==0 (
  echo [cockpit] already running on :%COCKPIT_PORT%
  start "" http://127.0.0.1:%COCKPIT_PORT%/
  exit /b 0
)

set REPO=%~1
if "%REPO%"=="" set REPO=%CD%
set COCKPIT_REPO=%REPO%

start "" /b cmd /c "timeout /t 2 >nul 2>nul & start "" http://127.0.0.1:%COCKPIT_PORT%/"
%PY% "%HERE%src\server.py"
