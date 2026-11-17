@echo off
rem Shared runner for the .bat files in the project folder.
rem
rem Runs "python -m omniosint <arguments>" with the project's virtual
rem environment. When the calling .bat file was opened by double-clicking it
rem (its name, in OMNI_LAUNCHER, appears in this window's command line), the
rem window stays open at the end so the messages can be read. Set
rem OMNIOSINT_NO_PAUSE=1 to never pause (scripts and CI).
setlocal EnableExtensions EnableDelayedExpansion

for %%I in ("%~dp0..\..") do set "OMNI_ROOT=%%~fI"
set "OMNI_PY=%OMNI_ROOT%\.venv\Scripts\python.exe"
set "RC=0"

set "PAUSE_AT_END=0"
if defined OMNI_LAUNCHER if not defined OMNIOSINT_NO_PAUSE (
    if /i not "!CMDCMDLINE:%OMNI_LAUNCHER%=!"=="!CMDCMDLINE!" set "PAUSE_AT_END=1"
)

if not exist "%OMNI_PY%" (
    echo.
    echo OmniOSINT is not installed in this folder yet. Run install.bat first.
    set "RC=1"
    goto :finish
)

set "PYTHONUTF8=1"
"%OMNI_PY%" -m omniosint %*
set "RC=!ERRORLEVEL!"

:finish
if "%PAUSE_AT_END%"=="1" (
    echo.
    if "!RC!"=="0" (
        if defined OMNI_STAYS_RUNNING echo You can close this window. OmniOSINT keeps running until you run stop.bat.
    )
    pause
)
exit /b !RC!
