# game-server-deployment-discord-bot

A Discord bot that starts and stops dedicated game servers (Valheim, Factorio, Enshrouded, Abiotic Factor, Windrose) on Hetzner Cloud via slash commands. Each server gets a fixed DNS name on deSEC.io, and its save data is backed up with restic on stop; see [CLAUDE.md](CLAUDE.md) for architecture and workflow details.

## Setup

1. `cp discord-bot.env.example discord-bot.env` and `cp job-runner.env.example job-runner.env`, then fill them in (Discord token/webhooks, Hetzner token, restic credentials, `DESEC_TOKEN`/`DESEC_ZONE`, per-game settings).
2. `docker compose up --build`

## DNS (deSEC.io)

Each game server is published as `<game>.<DESEC_ZONE>` A (plus AAAA for IPv6-capable games). The job-runner verifies token and zone with one GET before creating a server (`/start` is refused if it fails), publishes after creation, and clears the records after a successful stop. `DESEC_TOKEN` and `DESEC_ZONE` are both required. TTL is the constant `TTL` in `discord_bot/dns.py` (900 = the zone's deSEC `minimum_ttl`; deSEC support can lower it on request).

### Zone

Create the zone (e.g. `games.example.tld`) in deSEC, then delegate it from the parent DNS: NS records `ns1.desec.io` and `ns2.desec.org`, plus the DS records deSEC shows for the zone.

### Token

| Option | How | If the token leaks |
|---|---|---|
| 1. Unrestricted | Web UI, https://desec.io/tokens | Every domain in the deSEC account. Fine while the account holds only the game zone (current choice). |
| 2. Zone-wide | API only (the web UI cannot set policies): default deny + one write policy for the zone | Anything in that zone, nothing else in the account. |
| 3. Per-record | API only: default deny + one write policy per game for A and AAAA | Those ten records only. |

For options 2 and 3, create an admin token with `perm_manage_tokens` in the web UI, then:

```sh
ADMIN=<admin token>
ZONE=games.example.tld
api() { curl -sS -H "Authorization: Token $ADMIN" -H "Content-Type: application/json" "$@"; }

# Create the job-runner token. Response has "id" and "token" (token is shown once -> DESEC_TOKEN).
api -X POST https://desec.io/api/v1/auth/tokens/ \
  -d '{"name":"game-server-job-runner","perm_create_domain":false,"perm_delete_domain":false,"perm_manage_tokens":false}'
ID=<id from response>
P=https://desec.io/api/v1/auth/tokens/$ID/policies/rrsets/

# Default policy first (required before any specific policy): deny writes.
api -X POST "$P" -d '{"domain":null,"subname":null,"type":null,"perm_write":false}'

# Option 2: write access to the whole zone
api -X POST "$P" -d "{\"domain\":\"$ZONE\",\"subname\":null,\"type\":null,\"perm_write\":true}"

# Option 3 (instead of option 2): write access per game record
for g in valheim factorio enshrouded abiotic-factor windrose; do
  for t in A AAAA; do
    api -X POST "$P" -d "{\"domain\":\"$ZONE\",\"subname\":\"$g\",\"type\":\"$t\",\"perm_write\":true}"
    sleep 1  # deSEC throttles writes; avoids 429
  done
done
```

Notes:

- Reads are allowed for every token regardless of policy; policies only restrict writes.
- Check the scoping: a write for an unlisted subname must return 403:
  `curl -s -o /dev/null -w '%{http_code}\n' -X PUT -H "Authorization: Token <job-runner token>" -H "Content-Type: application/json" https://desec.io/api/v1/domains/games.example.tld/rrsets/ -d '[{"subname":"scope-test","type":"A","ttl":900,"records":["192.0.2.1"]}]'`
- Revoke the admin token afterwards, or at least keep it out of the job-runner.
- New game: add its A/AAAA policies (option 3).

### Verify

`dig @ns1.desec.io valheim.games.example.tld A` returns the server IP after `/start`,
and an empty answer after `/stop`.
