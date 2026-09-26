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
| 1. Unrestricted | Web UI, https://desec.io/tokens | Every domain in the deSEC account. Only acceptable while the account holds nothing but the game zone. |
| 2. Zone-wide | API only (the web UI cannot set policies): default deny + one write policy for the zone | Anything in that zone, nothing else in the account. **Current choice.** |
| 3. Per-record | API only: default deny + one write policy per game for A and AAAA | Those ten records only. |

Option 2, step by step. Create a temporary admin token in the web UI (https://desec.io/tokens, enable **manage tokens**), then run this from any shell with `curl` and `jq`:

```sh
ADMIN=<admin token>          # temporary, delete it in the UI afterwards
ZONE=games.example.tld
api() { curl -sS -H "Authorization: Token $ADMIN" -H "Content-Type: application/json" "$@"; }

# 1. Create the job-runner token (no domain create/delete, no token management).
RESP=$(api -X POST https://desec.io/api/v1/auth/tokens/ \
  -d '{"name":"game-server-job-runner","perm_create_domain":false,"perm_delete_domain":false,"perm_manage_tokens":false}')
ID=$(echo "$RESP" | jq -r .id)
TOKEN=$(echo "$RESP" | jq -r .token)   # shown only once -> DESEC_TOKEN in job-runner.env

# 2. Default policy first (required): deny writes everywhere ...
P=https://desec.io/api/v1/auth/tokens/$ID/policies/rrsets/
api -X POST "$P" -d '{"domain":null,"subname":null,"type":null,"perm_write":false}'
sleep 1
# 3. ... then allow writes in the game zone only.
api -X POST "$P" -d "{\"domain\":\"$ZONE\",\"subname\":null,\"type\":null,\"perm_write\":true}"

# 4. Check: the new token can read the zone (200), cannot manage tokens (403).
curl -s -o /dev/null -w 'zone read: %{http_code}\n'   -H "Authorization: Token $TOKEN" https://desec.io/api/v1/domains/$ZONE/
curl -s -o /dev/null -w 'token list: %{http_code}\n'  -H "Authorization: Token $TOKEN" https://desec.io/api/v1/auth/tokens/
echo "DESEC_TOKEN=$TOKEN"
```

Put the printed `DESEC_TOKEN` into `job-runner.env`, then delete the admin token in the web UI (or `api -X DELETE https://desec.io/api/v1/auth/tokens/<admin id>/`).

Option 3 (per-record) is the same sequence with step 3 replaced by one policy per game record:

```sh
for g in valheim factorio enshrouded abiotic-factor windrose; do
  for t in A AAAA; do
    api -X POST "$P" -d "{\"domain\":\"$ZONE\",\"subname\":\"$g\",\"type\":\"$t\",\"perm_write\":true}"
    sleep 1  # deSEC throttles writes
  done
done
```

Notes:

- Reads are allowed for every token regardless of policy; policies only restrict writes.
- deSEC throttles writes (~2/s per zone); the `sleep 1` lines avoid 429.
- A new game under option 3 needs its own A/AAAA policies.

### Verify

`dig @ns1.desec.io valheim.games.example.tld A` returns the server IP after `/start`,
and an empty answer after `/stop`.
