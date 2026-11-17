@echo off
rem Updates OmniOSINT in place: stops it, backs up the database, fetches the new
rem version (git checkouts), re-runs setup and starts it again. Data is kept.
rem Options: -NoPull  -SkipBackup  -NonInteractive
setlocal
set "OMNI_LAUNCHER=%~nx0"
set "OMNI_PS_SCRIPT=%~dp0scripts\windows\update.ps1"
call "%~dp0scripts\windows\powershell.cmd" %*
exit /b %ERRORLEVEL%
