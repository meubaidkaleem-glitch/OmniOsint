@echo off
rem Restores a backup made with backup.bat. OmniOSINT must be stopped first.
rem The current data is backed up before it is replaced.
rem Usage: restore.bat PATH\TO\omniosint-backup-....zip
rem Without a path, lists the available backups.
setlocal
set "OMNI_LAUNCHER=%~nx0"
if "%~1"=="" (
    call "%~dp0scripts\windows\omniosint.cmd" backup list
    echo.
    echo Usage: restore.bat PATH\TO\omniosint-backup-....zip
    exit /b 2
)
call "%~dp0scripts\windows\omniosint.cmd" backup restore %*
exit /b %ERRORLEVEL%
