@echo off
rem Removes what install.bat created in this folder. Keeps your data folder
rem and the database unless you explicitly choose otherwise.
rem Options: -Yes (no questions; data kept)  -RemoveData
setlocal
set "OMNI_LAUNCHER=%~nx0"
set "OMNI_PS_SCRIPT=%~dp0scripts\windows\uninstall.ps1"
call "%~dp0scripts\windows\powershell.cmd" %*
exit /b %ERRORLEVEL%
