@echo off
rem Stops OmniOSINT cleanly (API and background worker).
setlocal
set "OMNI_LAUNCHER=%~nx0"
call "%~dp0scripts\windows\omniosint.cmd" stop %*
exit /b %ERRORLEVEL%
