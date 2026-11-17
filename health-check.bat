@echo off
rem Reports whether OmniOSINT is running and healthy, then checks the whole
rem installation. Exit code 0 only when it is running and healthy and no
rem installation check failed.
setlocal
set "OMNI_LAUNCHER=%~nx0"
set "OMNIOSINT_NO_PAUSE_SAVED=%OMNIOSINT_NO_PAUSE%"
set "OMNIOSINT_NO_PAUSE=1"
call "%~dp0scripts\windows\omniosint.cmd" status --check
set "STATUS_RC=%ERRORLEVEL%"
echo.
set "OMNIOSINT_NO_PAUSE=%OMNIOSINT_NO_PAUSE_SAVED%"
call "%~dp0scripts\windows\omniosint.cmd" doctor
set "DOCTOR_RC=%ERRORLEVEL%"
if not "%STATUS_RC%"=="0" exit /b %STATUS_RC%
exit /b %DOCTOR_RC%
