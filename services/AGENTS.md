# services/ agent notes

Python **prototype / parity** only. Root [`AGENTS.md`](../AGENTS.md) still applies.

## Rules

- Authoritative direction is `server/` (Rust). Do not add new long-term features
  only in Python when the Rust port already owns that plane.
- Preserve fixtures and measured behaviours for parity tests.
- Retirement: when Rust acceptance for a feature is green, mark the Python path
  for deletion (see PLAN-master-platform kill-Python phase).
- Gateway stdlib; world may use pyOpenSSL for DTLS until cutover.
