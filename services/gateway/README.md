# Gateway

The gateway is the client's HTTP entry point (`127.0.0.1:8080`), usually behind
Caddy on `:443`. It is a single Python process with standard-library HTTP; it
is not split into microservices.

Start it through the root CLI:

```powershell
python ef.py gateway start
```

For the full development stack use `python ef.py dev`. The supported route
behavior and traffic capture are documented in
[`services/docs/GATEWAY.md`](../docs/GATEWAY.md). Traffic and body sidecars are
local data and may contain private session information.
