@echo off
rem Installs OmniOSINT: checks prerequisites, creates the Python environment,
rem builds the web interface and prepares the database. Safe to run again.
rem Options are passed to setup.ps1, e.g.:  install.bat -NonInteractive -Database skip
setlocal
set "OMNI_LAUNCHER=%~nx0"
set "OMNI_PS_SCRIPT=%~dp0setup.ps1"
call "%~dp0scripts\windows\powershell.cmd" %*
exit /b %ERRORLEVEL%
