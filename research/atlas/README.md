# Research atlas

The atlas is the durable registry for observed client behavior and confirmed
wire facts. Update it when evidence is found; a chat note or status summary is
not a substitute.

| File | Owns |
| --- | --- |
| `ontology/` | Purpose, lifecycle, confidence, relations — scalable concept files ([README](ontology/README.md)) |
| `endpoints.json` | Observed REST operation, method, path, query, and auth facts |
| `models.json` | Exact request/response keys, types, requiredness, and evidence |
| `errors.json` | Observed errors and confirmed causes |
| `levers.md` | Client settings, runtime controls, and their measured effects |
| `client-functions.json` | Confirmed native function names, VAs, behavior, and evidence |
| `presence-live-capture.json` | Live capture of the payloads the client's unmarshal receives, with the hook site and the argument correction |
| `presence-codecs.json` | The six actor-replication message types a server needs, with identity and the record of which decoding routes were tried |
| `builds.json` | Installed client build identity (full SHA-256), which build each body of evidence was measured on, and per-session official-service facts |
| `decomp-campaign.json` | Committed phase manifest for the incremental decompilation campaign |
| `client-map/` | Growing per-screen knowledge plan (launch, login, server select, character select, world entry, in-world) |
| `observed-endpoints.json` | Gateway-generated endpoint families and captured examples |
| `openapi.json` | Gateway-generated OpenAPI view of captured traffic |

## Evidence rules

- Record the exact wire spelling and type. Mark an unverified field with
  `"evidence": "guessed"`.
- Keep candidate function names separate. Only add a name to
  `client-functions.json` after checking the function body or a second signal;
  include its VA and `found_by` method.
- Keep raw tokens, identities, and full payloads in ignored
  `research/sessions/`. Commit only redacted examples and curated findings.
- Identify the build before recording a fact that depends on the binary. A VA,
  offset or wire type measured on one build is not evidence for another; record
  which build it came from in `builds.json`.
- Gateway traffic writes `observed-endpoints.json`; run `python az.py doc` to
  regenerate `openapi.json` after a play session.

`client-functions.json` is hand-maintained evidence, not decompiler output.
Per-machine Ghidra projects, pseudocode, and caches live under the ignored
local work directory.
