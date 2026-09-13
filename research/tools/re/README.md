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
python tools\re\validate.py
python tools\re\disk.py --out sessions\disk_snapshot
python tools\re\strings.py --out sessions\static_exe
python tools\re\endpoints.py --session sessions\<session>
python tools\re\net.py analyze sessions\<session>\network\pktmon.pcapng
```

`memory.py` is a hard no while EAC EOS is live. See `docs/EAC.md`.
