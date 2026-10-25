# 0009. Daily loop is native `az.dev`; Compose is Linux/CI/prod

Date: 2026-10-24
Status: accepted

## Context

We need both a fast Windows loop (private client + Caddy + gateway/world) and
a Linux-shaped server path for Docker/K8s. Running the whole stack in Compose
on Windows is slow (VM FS sync), hurts hot reload, and fights the private
client / host routing tools.

Industry default for app code: **native process + containerized dependencies**.

## Decision

1. **Day-to-day development (Windows):** `python ef.py setup --core`,
   `python ef.py doctor`, `python ef.py dev` (+ `python ef.py game`).
   Gateway/world/Caddy are host processes. Logs under `.azoth/logs/`.
2. **Compose (`deploy/local/compose.yml`):** Linux server images for CI,
   clone-on-Linux, and production-like smoke — **not** the default edit loop
   while iterating Rust or Python against a private client.
3. Later hybrid: Postgres/Redis in Compose; `channel`/`region`/`world` still
   native on the host until those services exist as hard deps.
4. Never require Docker Desktop to enter the world on a Windows checkout.

## Consequences

- Contributors learn one loop: `az.dev`.
- Compose stays maintained for Linux parity (ADR 0004 OpenSSL in images).
- Docs and agent prompts must not say “compose up to develop.”

## Alternatives considered

| Option | Why not |
| --- | --- |
| Compose-everything on Windows | Slow; bad for client + host routing |
| Native-only forever | Blocks Linux CI/prod |
| Dev containers for Rust only | Optional later; not the default today |
