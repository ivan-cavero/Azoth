# Reverse-engineering helpers

Disk vs runtime stay separate.

```
DISK (always safe)                 RUNTIME (outside the process)
-------------------------------    --------------------------------
disk.py     install / PAK index    capture/Start-NwCapture.bat
strings.py  EXE file strings       net.py analyze <pcapng>
eac.py      EAC Settings.json      log.py ingest
endpoints.py  host catalog         Game.log + pktmon + DNS
memory.py   refuses live RPM
validate.py compile + env check
```

```bat
python tools\reversing\validate.py
python tools\reversing\disk.py --out sessions\disk_snapshot
python tools\reversing\strings.py --out sessions\static_exe
python tools\reversing\endpoints.py --session sessions\<session>
python tools\reversing\net.py analyze sessions\<session>\network\pktmon.pcapng
```

`memory.py` is a hard no while EAC EOS is live. See `docs/EAC.md`.
