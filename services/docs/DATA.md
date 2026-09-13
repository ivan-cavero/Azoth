# Data

Postgres. The world tick **never** waits on SQL (write-behind).

```
accounts          id, persona, steam_id_hash NULL  -- private does not use Steam
characters        id uuid, account_id, name, appearance jsonb, world_id
worlds            id, name, rep_host, rep_port
login_tickets     ticket_id, world_id, character_id, issued_at, consumed_at
```

The REP bind lives in `worlds`, not duplicated on the ticket. Inventory and world_state come later.

Seed v1: one world `azoth-1`.
