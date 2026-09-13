# Datos

Postgres. El tick del world **nunca** espera a SQL (write-behind).

```
accounts          id, persona, steam_id_hash NULL  -- private no usa Steam
characters        id uuid, account_id, name, appearance jsonb, world_id
worlds            id, name, rep_host, rep_port
login_tickets     ticket_id, world_id, character_id, issued_at, consumed_at
```

Bind REP vive en `worlds`, no duplicado en el ticket. Inventario y world_state entran más tarde.

Seed v1: un mundo `azoth-1`.
