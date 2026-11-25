@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-VoiceMacro.ps1"
if errorlevel 1 echo Installation needs attention. Read the message above.
pause
