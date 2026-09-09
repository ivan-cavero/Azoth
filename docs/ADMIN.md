# Permisos admin controlados (tarea programada elevada) — LEER AL INICIAR SESIÓN

> **Regla para el agente**: antes de empezar a probar nada, comprueba si esta
> sesión necesita tareas admin (redirect de `hosts`, Caddy en `:443`,
> `switch-mode.ps1`). Si las necesita, usa el **puente admin** de abajo —
> NO pide UAC, NO caduca. Si la tarea `AzothAdminProxy` no existe, entonces sí
> pide al operador el setup de UNA vez (sección "Setup").
> Caché de gsudo descartada: expiraba en medio de sesiones largas y con la
> consola del agente cada árbol de proceso re-pedía UAC.

## Por qué

El modo private necesita dos cosas que solo un admin puede hacer:

1. Escribir el bloque `# >>> AZOTH PRIVATE >>>` en `C:\Windows\System32\drivers\etc\hosts`
   (redirige `tokenservice.amazongames.com` etc. a `127.0.0.1`).
2. Arrancar Caddy en el puerto `:443` (TLS del juego).

El agente corre como usuario normal (`ivan\ivang`, no admin).

## El puente admin (lo que se usa en el día a día)

Tarea programada `AzothAdminProxy` que corre como admin (`RunLevel Highest`)
y ejecuta lo que encuentre en un fichero de comandos:

- **Comando a ejecutar**: `%LOCALAPPDATA%\Azoth\admin\cmd.txt` (una línea)
- **Salida**: `%LOCALAPPDATA%\Azoth\admin\out.txt` (se sobrescribe en cada run)

Uso (todo sin UAC, sin admin):

```powershell
$dir = "$env:LOCALAPPDATA\Azoth\admin"
# 1) escribir el comando
"whoami /groups | findstr /C:S-1-16-12288" | Set-Content "$dir\cmd.txt" -Encoding ascii
# 2) lanzar la tarea elevada
Start-ScheduledTask -TaskName 'AzothAdminProxy'
# 3) esperar a que termine y leer la salida
Start-Sleep -Seconds 2
Get-Content "$dir\out.txt"
```

Detalles:

- El proxy ejecuta **una sola línea** de comando por run (`Invoke-Expression`).
  Para varias cosas, encadénalas con `;` o llama a un script: 
  `powershell -NoProfile -File F:\Azoth\emulator\deploy\switch-mode.ps1 private`
- `out.txt` guarda stdout+stderr. Si dice `NO-CMD`, no había `cmd.txt`.
- La tarea tiene `ExecutionTimeLimit = 10 min`. Para Caddy (largo), ver abajo.
- Al lanzar la tarea, `Start-ScheduledTask` devuelve inmediato; si el comando
  es lento, espera con un bucle comprobando si `out.txt` cambió.

### Procesos largos (Caddy, etc.)

La tarea mata el proceso a los 10 min. Para Caddy, el patrón es: el proxy
ejecuta un comando que **desacopla** el proceso largo:

```powershell
# cmd.txt (una línea):
Start-Process -FilePath F:\Azoth\emulator\deploy\bin\caddy.exe -ArgumentList 'run','--config','F:\Azoth\emulator\deploy\Caddyfile.json' -WindowStyle Hidden -RedirectStandardOutput $env:TEMP\azoth-caddy.out.log -RedirectStandardError $env:TEMP\azoth-caddy.err.log
```

El `Start-Process` vuelve al momento y Caddy queda corriendo elevado, ajeno a
la tarea programada.

### Parar Caddy

```powershell
# cmd.txt:
Stop-Process -Name caddy -Force -ErrorAction SilentlyContinue; 'stopped'
```

## Setup (ya hecho en esta máquina; reproducir si falta)

1. **proxy.ps1** ( `%LOCALAPPDATA%\Azoth\admin\proxy.ps1`):

```powershell
# Azoth admin proxy: ejecuta el comando de cmd.txt como admin y guarda la salida.
$dir = "$env:LOCALAPPDATA\Azoth\admin"
$f = Join-Path $dir 'cmd.txt'
$out = Join-Path $dir 'out.txt'
if (-not (Test-Path $f)) { Set-Content -Path $out -Value 'NO-CMD' -Encoding utf8; exit 1 }
$cmd = Get-Content $f -Raw
try {
  Invoke-Expression $cmd *>&1 | Out-String | Set-Content -Path $out -Encoding utf8
  exit 0
} catch {
  Set-Content -Path $out -Value ("ERROR: " + $_.Exception.Message) -Encoding utf8
  exit 1
}
```

2. **La tarea** (esto es lo único que pide UAC, una vez en la vida):

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\Users\ivang\AppData\Local\Azoth\admin\proxy.ps1'
$principal = New-ScheduledTaskPrincipal -UserId 'IVAN\ivang' -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::FromMinutes(10))
Register-ScheduledTask -TaskName 'AzothAdminProxy' -Action $action -Principal $principal -Settings $settings -Force
```

## Trampas conocidas

- El backup de `hosts` lo hace `switch-mode.ps1` solo (`hosts.azoth-bak-*`).
  Nunca editar `hosts` a mano.
- `cmd.txt` en **ASCII** (el proxy lo lee con `Get-Content -Raw`; evita BOM).
- Si el comando falla silenciosamente, revisa `out.txt` (contiene el error).
- Seguridad: cualquiera que pueda escribir `cmd.txt` ejecuta como admin. Está
  en el perfil del usuario, mismo riesgo que tener una consola admin abierta.
  Si el equipo es compartido, eliminar la tarea:
  `Unregister-ScheduledTask -TaskName 'AzothAdminProxy' -Confirm:$false` (admin).
