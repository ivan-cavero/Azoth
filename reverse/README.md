# Client reverse engineering

This directory contains the tools and local output for analyzing the New World
client. It does not contain runtime server code.

| Path | Purpose |
| --- | --- |
| `tools/` | PE/xref analysis, Ghidra decompilation, PAK and asset readers |
| `probes/client/` | Build-specific live client probes, separate from routine scripts and server startup |
| `builds/<full-executable-sha256>/` | Ignored Ghidra project, function corpus, pseudocode, indexes, and logs for one client build |

Start with the [decompilation workflow](../research/docs/DECOMPILATION.md).
Run `python az.py setup` once to install the current locked Ghidra and JDK under
`.azoth/tools/`. Use `python az.py re decompile --symbol <confirmed-name>` for
a targeted function, or `python az.py re corpus` for full function coverage.
Generated output is local, keyed by the full executable SHA-256, and
regenerable. Run `python az.py re list` for the maintained workflow catalog.

Run `python az.py probe list` to browse one-off client probes and
`python az.py probe <name>` to execute one with the repo-local Python tools.
Each probe header records its question and build assumptions. These probes are
not part of routine server startup.

Confirmed names and evidence belong in
[`research/atlas/client-functions.json`](../research/atlas/client-functions.json).
Candidate names and pseudocode are analysis aids. They are not recovered
source; verify the behavior Azoth depends on against independent evidence.
