@echo off
REM ==GRoK== Local AI Control Room launcher (Windows)
setlocal
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-control-room.ps1" %*
