@echo off
title Azoth Game (Ctrl+C mata el juego, cerrar ventana tambien)
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -Command "& 'C:\Users\ivang\Desktop\Dev\NewWorldPrivateServer\launcher\src\Start-NwPrivate.ps1' -Watch *>&1 | Tee-Object -FilePath \"$env:LOCALAPPDATA\Azoth\azoth-game.log\""
