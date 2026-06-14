#!/bin/bash
# Idempotent installer for the green-axolotl update automation.
# Requires env: DOKPLOY_KEY, CRAFTY_JWT.  Optional: SSHC (ssh command).
#
# JSON request bodies are piped to the remote curl via stdin (--data @-) so no
# shell-quoting of bodies is needed (the playit compose contains `version: '3'`).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SSHC="${SSHC:-ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210}"
ORG="eFbswAqh7vlP_F7SfdS8D"
PLAYIT_COMPOSE="Up4B06-EaIzJuYH3mxgTj"
PLAYIT_WEBHOOK="FohNmoNN_pzIgkfljoAJo"
: "${DOKPLOY_KEY:?set DOKPLOY_KEY}"
: "${CRAFTY_JWT:?set CRAFTY_JWT}"

apipost() {  # apipost <proc>   — JSON body on stdin
  $SSHC -- "curl -fsS -X POST 'http://localhost:3000/api/$1' \
    -H 'x-api-key: $DOKPLOY_KEY' -H 'Content-Type: application/json' --data @-"
}
apiget() { $SSHC -- "curl -fsS 'http://localhost:3000/api/$1' -H 'x-api-key: $DOKPLOY_KEY'"; }

echo "==> 1. install updater + config into crafty_container volume"
$SSHC -- "docker exec -i crafty_container sh -c 'mkdir -p /crafty/import/autoupdate/logs'"
$SSHC -- "docker exec -i crafty_container sh -c 'cat > /crafty/import/autoupdate/mc-autoupdate.py'" < "$HERE/mc-autoupdate.py"
python3 - "$HERE/config.example.json" "$CRAFTY_JWT" <<'PY' > /tmp/config.rendered.json
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg["crafty_jwt"] = sys.argv[2]
print(json.dumps(cfg, indent=2))
PY
$SSHC -- "docker exec -i crafty_container sh -c 'cat > /crafty/import/autoupdate/config.json && chmod 600 /crafty/import/autoupdate/config.json'" < /tmp/config.rendered.json
rm -f /tmp/config.rendered.json
echo "    installed."

echo "==> 2. fix playit compose (image :1.0 + restart: unless-stopped)"
apiget "compose.one?composeId=$PLAYIT_COMPOSE" | python3 -c '
import json, sys
c = json.load(sys.stdin); f = c["composeFile"]
f = f.replace("playit-agent:0.17", "playit-agent:1.0")
if "restart:" not in f:
    f = f.replace("network_mode: host", "network_mode: host\n    restart: unless-stopped")
print(json.dumps({"composeId": sys.argv[1], "composeFile": f}))
' "$PLAYIT_COMPOSE" | apipost "compose.update" >/dev/null
echo "    redeploying playit..."
$SSHC -- "curl -fsS -X POST 'http://localhost:3000/api/deploy/compose/$PLAYIT_WEBHOOK'" >/dev/null
echo "    playit updated + redeployed."

echo "==> 3. create/update nightly schedule (3:30 UTC)"
EXISTING=$(apiget "schedule.list?id=$ORG&scheduleType=dokploy-server" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(next((s["scheduleId"] for s in d if s["name"] == "mc-nightly-maintenance"), ""))')
python3 -c '
import json, sys
script = open(sys.argv[1]).read()
body = {"name": "mc-nightly-maintenance", "cronExpression": "30 3 * * *",
        "scheduleType": "dokploy-server", "shellType": "bash", "enabled": True,
        "organizationId": sys.argv[2], "script": script}
if sys.argv[3]:
    body["scheduleId"] = sys.argv[3]
print(json.dumps(body))
' "$HERE/nightly-maintenance.sh" "$ORG" "$EXISTING" \
  | apipost "$([ -n "$EXISTING" ] && echo schedule.update || echo schedule.create)" >/dev/null
echo "    schedule $([ -n "$EXISTING" ] && echo updated || echo created)."

echo "==> done. Manual dry-run:"
echo "    $SSHC -- \"docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py --dry-run\""
