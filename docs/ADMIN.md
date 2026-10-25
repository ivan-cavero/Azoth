# Local Windows operations

Use `python ef.py mode status` to check routing; this command does not require
elevation. Switching `private` or `official` edits the Windows hosts file and
requires an elevated PowerShell session:

```powershell
Start-Process powershell.exe -Verb RunAs
```

In that elevated shell, change to the repository root and run:

```powershell
python ef.py mode private
# Restore the official route when finished:
python ef.py mode official
```

The project CLI owns the hidden Caddy, gateway, and world processes. Use
`python ef.py dev`, `python ef.py dev status`, and `python ef.py dev stop`;
logs and process state are under ignored `.azoth/`. Caddy listens only on
loopback. Its persistent CA and certificate data is under `.azoth/caddy/`.

Do not create or use an elevated scheduled task that executes commands from a
writable text file. No such bridge is required for Azoth.
