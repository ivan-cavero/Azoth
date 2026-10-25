---
name: everfall-decompile
description: >-
  Decompile one New World client function and record what it means for Everfall.
  Use for Ghidra, a virtual address, a wire codec, or static client analysis.
---

# One function

Also load `protocols` and `security` before any live attach. This skill does not attach Frida.

1. Take the one question from `STATUS.md`.
2. Confirm the client SHA-256 before trusting an address.
3. `python ef.py re decompile` on that function. Pseudocode is not source.
4. Write the plain-language result, the address, the build, and what is still unknown into `research/atlas/meanings.md` or `research/atlas/client-functions.json`. Mark guesses as guessed.
5. Stop.

Corpora under `reverse/builds/<sha256>/` stay on disk. Do not read a corpus into the chat.
