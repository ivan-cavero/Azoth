# Contributor loop

Day to day on Everfall. The current step is `STATUS.md`. The rebuild rule is
`docs/PLAN.md`.

## Clone

```text
git clone <repo>
cd <repo>
.\az.ps1 setup          # Windows, once: pinned Python and Caddy
python ef.py doctor
python ef.py dev        # gateway, world, Caddy
python ef.py game       # private client
```

Logs are under `.azoth/logs/`. `python ef.py setup --re` adds Ghidra. That
download is large. `python ef.py setup --purge` removes the local tools.

Compose under `deploy/local/` is for Linux and CI. The Windows loop is
`python ef.py dev`.

There is no Rust workspace. Do not run `cargo` against `server/`. When a row
in `research/atlas/meanings.md` names its fields, `docs/PLAN.md` says how the
first crate is allowed to appear.

## Tests

```text
python ef.py gateway test
python ef.py world test
python ef.py doctor
```

A change to the lab should say what the client did, or what a unit test now
locks. A green test that only compares captured bytes does not close a
meaning row.
