@echo off
rem Stops and starts OmniOSINT again.
setlocal
set "OMNI_LAUNCHER=%~nx0"
set "OMNI_STAYS_RUNNING=1"
call "%~dp0scripts\windows\omniosint.cmd" restart %*
exit /b %ERRORLEVEL%
