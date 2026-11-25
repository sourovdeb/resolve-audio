@echo off
where winget >nul 2>nul
if errorlevel 1 (
    echo Install Python 3 and FFmpeg manually. See START-HERE.html.
    pause
    exit /b 1
)
py -3 --version >nul 2>nul
if errorlevel 1 (
    python --version >nul 2>nul
    if errorlevel 1 winget install --id Python.Python.3.12 --exact --source winget
)
where ffmpeg >nul 2>nul
if errorlevel 1 winget install --id Gyan.FFmpeg --exact --source winget
echo Close and reopen Resolve after installing the tools.
pause
