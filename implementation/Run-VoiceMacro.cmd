@echo off
pushd "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    echo Install Python 3, then reopen this window.
    pause
    exit /b 1
)
py -3 voice_macro_console.py %*
if errorlevel 1 pause
popd
