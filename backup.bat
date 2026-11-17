@echo off
rem Backs up the OmniOSINT database and settings to a zip archive in the
rem backups folder of your data directory. Archives are not encrypted.
rem Options: --label NAME  --output FOLDER
setlocal
set "OMNI_LAUNCHER=%~nx0"
call "%~dp0scripts\windows\omniosint.cmd" backup create %*
exit /b %ERRORLEVEL%
