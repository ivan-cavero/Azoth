@echo off
title New World Capture
cd /d "%~dp0"
echo.
echo Will ask for Administrator once (NIC capture).
echo Accept. One window stays open.
echo Do NOT press ENTER until you have played ~10 minutes.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-NwCapture.ps1" -SkipStatic
if errorlevel 1 pause
