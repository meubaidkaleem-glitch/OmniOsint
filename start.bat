@echo off
rem Starts OmniOSINT: validates the configuration, checks the database,
rem starts the API and the background worker, waits until they report healthy
rem and opens the interface in your browser.
rem Options: --no-open (do not open the browser)  --json
setlocal
set "OMNI_LAUNCHER=%~nx0"
set "OMNI_STAYS_RUNNING=1"
call "%~dp0scripts\windows\omniosint.cmd" start --open %*
exit /b %ERRORLEVEL%
