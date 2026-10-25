# Local compose (Linux / CI / prod-like — not daily Windows dev)

Daily private-client work uses **`python ef.py dev`** on the host
([ADR 0009](../../docs/adr/0009-native-dev-vs-compose.md)).

```bash
docker compose -f deploy/local/compose.yml up --build
```

Publishes `channel` :8081, `region` :8080, `world` UDP :36000.
Requires Docker Engine. First build compiles Rust inside Linux — slow once.
