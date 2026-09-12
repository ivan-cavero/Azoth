@echo off
title Azoth Gateway :8080 (cerrar mata el proceso)
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -Command "$env:PYTHONPATH='C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\emulator\apps\gateway\src'; python -m azoth_gateway --port 8080 *>&1 | Tee-Object -FilePath \"$env:LOCALAPPDATA\Azoth\azoth-gateway.log\""
