# server — the Rust workspace

Started 2026-10-15 with the one piece `docs/ROADMAP.md` section 4 names as genuinely
port-ready: the Javelin wire codecs. The rest of the workspace shape is described in
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) and is written when a second
authoritative behavior exists to give it a shape.

## crates/protocol

`varint` (the prefix varint) and `bundle` (the type-0x08 StateBundle: prologue, record
sequence, fragment grammar), ported from the Python reference in
`services/world/src/azoth_world/javelin/`. **Zero dependencies** — the repository's
standard-library preference applies to the port too.

```text
cd server
cargo test -p azoth-protocol
```

12 tests: 8 unit (round-trips, the prologue layout check, the widening-counter
re-encode, fragment slicing) and 4 parity tests against the captured corpus.

## The parity fixture

`crates/protocol/tests/fixtures/state-bundles.txt` is generated FROM the Python codecs by
`scripts/gen-protocol-fixture.py`; the Rust tests read it. That is the ROADMAP's
"compare Rust and Python at the wire boundary using the same fixtures" rule in practice,
and it means the expectation cannot be a second hand-written guess that drifts:

```text
python scripts/gen-protocol-fixture.py           # regenerate
python scripts/gen-protocol-fixture.py --check   # fail if it would change
```

The parity tests assert, among other things:

- every captured varint case encodes to the exact bytes Python produces and decodes back;
- all 49 captured bundle bodies decode, **re-encode identically**, and report the same
  replication counter, payload length and first record header — so the port cannot
  silently change what a client would receive;
- the record-1 (local-player metadata) fragment boundaries and `(key, type)` pairs
  measured from the CLIENT's own readers, which cannot be recomputed from the bytes;
- that the captured player position pair is still at spawn-payload offset **38332** while
  being **absent** from the streamed record-1 bundle. This doubles as a regression guard
  on the position anchor: if the capture or the parser changes, the test fails instead of
  the server silently losing its position authority.

## What is deliberately not here

The replay pump and the response-scheduling policy in
`services/world/src/azoth_world/rep.py`. Those exist to make a captured session behave and
are exactly what an authoritative server replaces; porting them would give the port the
same shape as the prototype.
