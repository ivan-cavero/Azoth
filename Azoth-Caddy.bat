@echo off
title Azoth Caddy :443 (cerrar mata el proceso)
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -Command "& 'C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\emulator\deploy\bin\caddy.exe' run --config 'C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\emulator\deploy\Caddyfile.json' 2>&1 | Tee-Object -FilePath \"$env:LOCALAPPDATA\Azoth\azoth-caddy.log\""
