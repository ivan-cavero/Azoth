# Controlled admin permissions (elevated scheduled task) — READ AT SESSION START

> **Agent rule:** before testing anything, check whether this session needs admin
> tasks (`hosts` redirect, Caddy on `:443`, `switch-mode.ps1`). If it does, use the
> **admin bridge** below — it does NOT prompt UAC and does NOT expire. If the
> `AzothAdminProxy` task does not exist, then ask the operator for the ONE-TIME
> setup ("Setup" section).
> The gsudo cache was discarded: it expired mid-session and with the agent console
> each process tree re-prompted UAC.

## Why

Private mode needs two things only an admin can do:

1. Writing the `# >>> AZOTH PRIVATE >>>` block into `C:\Windows\System32\drivers\etc\hosts`
   (redirects `tokenservice.amazongames.com` etc. to `127.0.0.1`).
2. Starting Caddy on port `:443` (the game's TLS).

The agent runs as a normal user (`ivan\ivang`, not admin).

## The admin bridge (day-to-day)

Scheduled task `AzothAdminProxy` runs as admin (`RunLevel Highest`) and executes
whatever it finds in a command file:

- **Command to run**: `%LOCALAPPDATA%\Azoth\admin\cmd.txt` (one line)
- **Output**: `%LOCALAPPDATA%\Azoth\admin\out.txt` (overwritten on every run)

Usage (all without UAC, without admin):

```powershell
$dir = "$env:LOCALAPPDATA\Azoth\admin"
# 1) write the command
"whoami /groups | findstr /C:S-1-16-12288" | Set-Content "$dir\cmd.txt" -Encoding ascii
# 2) start the elevated task
Start-ScheduledTask -TaskName 'AzothAdminProxy'
# 3) wait for it to finish and read the output
Start-Sleep -Seconds 2
Get-Content "$dir\out.txt"
```

Details:

- The proxy executes **a single command line** per run (`Invoke-Expression`).
  For several things, chain them with `;` or call a script:
  `powershell -NoProfile -File <repo>\deploy\switch-mode.ps1 private`
- `out.txt` stores stdout+stderr. If it says `NO-CMD`, there was no `cmd.txt`.
- The task has `ExecutionTimeLimit = 10 min`. For Caddy (long-running), see below.
- `Start-ScheduledTask` returns immediately; if the command is slow, wait in a
  loop checking whether `out.txt` changed.

### Long-running processes (Caddy, etc.)

The task kills the process after 10 min. For Caddy the pattern is: the proxy
executes a command that **detaches** the long-running process:

```powershell
# cmd.txt (one line):
Start-Process -FilePath <repo>\deploy\bin\caddy.exe -ArgumentList 'run','--config','<repo>\deploy\Caddyfile.json' -WindowStyle Hidden -RedirectStandardOutput $env:TEMP\azoth-caddy.out.log -RedirectStandardError $env:TEMP\azoth-caddy.err.log
```

`Start-Process` returns immediately and Caddy keeps running elevated, detached
from the scheduled task.

### Stopping Caddy

```powershell
# cmd.txt:
Stop-Process -Name caddy -Force -ErrorAction SilentlyContinue; 'stopped'
```

## Setup (already done on this machine; reproduce if missing)

1. **proxy.ps1** (`%LOCALAPPDATA%\Azoth\admin\proxy.ps1`):

```powershell
# Azoth admin proxy: runs the cmd.txt command as admin and stores the output.
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

1. **The task** (the only step that asks UAC, once ever):

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\Users\ivang\AppData\Local\Azoth\admin\proxy.ps1'
$principal = New-ScheduledTaskPrincipal -UserId 'IVAN\ivang' -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::FromMinutes(10))
Register-ScheduledTask -TaskName 'AzothAdminProxy' -Action $action -Principal $principal -Settings $settings -Force
```

## Known traps

- The `hosts` backup is done by `switch-mode.ps1` itself (`hosts.azoth-bak-*`).
  Never edit `hosts` by hand.
- `cmd.txt` must be **ASCII** (the proxy reads it with `Get-Content -Raw`; avoid BOM).
- If a command fails silently, check `out.txt` (it contains the error).
- Security: anyone who can write `cmd.txt` runs commands as admin. It lives in the
  user profile — same risk as leaving an admin console open. On a shared machine,
  remove the task:
  `Unregister-ScheduledTask -TaskName 'AzothAdminProxy' -Confirm:$false` (admin).
