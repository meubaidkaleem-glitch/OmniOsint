@echo off
rem Shared runner for install.bat, update.bat and uninstall.bat: runs the
rem PowerShell script named in OMNI_PS_SCRIPT with the given arguments, for
rem this process only with -ExecutionPolicy Bypass (no system setting is
rem changed), and keeps a double-clicked window open at the end.
setlocal EnableExtensions EnableDelayedExpansion

set "PAUSE_AT_END=0"
if defined OMNI_LAUNCHER if not defined OMNIOSINT_NO_PAUSE (
    if /i not "!CMDCMDLINE:%OMNI_LAUNCHER%=!"=="!CMDCMDLINE!" set "PAUSE_AT_END=1"
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%OMNI_PS_SCRIPT%" %*
set "RC=!ERRORLEVEL!"

if "%PAUSE_AT_END%"=="1" (
    echo.
    pause
)
exit /b !RC!
