#!/bin/bash
# Idempotent installer for the green-axolotl update automation.
# Requires env: DOKPLOY_KEY, CRAFTY_JWT.  Optional: SSHC (ssh command).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SSHC="${SSHC:-ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210}"
ORG="eFbswAqh7vlP_F7SfdS8D"
PLAYIT_COMPOSE="Up4B06-EaIzJuYH3mxgTj"
PLAYIT_WEBHOOK="FohNmoNN_pzIgkfljoAJo"
SERVER_ID="394a3479-b8e9-4f4f-aa36-49c87eafe548"
: "${DOKPLOY_KEY:?set DOKPLOY_KEY}"
: "${CRAFTY_JWT:?set CRAFTY_JWT}"

api() {  # api <proc> <json-body>   (POST mutation through remote localhost)
  $SSHC -- "curl -fsS -X POST 'http://localhost:3000/api/$1' \
    -H 'x-api-key: $DOKPLOY_KEY' -H 'Content-Type: application/json' -d '$2'"
}
apiget() { $SSHC -- "curl -fsS 'http://localhost:3000/api/$1' -H 'x-api-key: $DOKPLOY_KEY'"; }

echo "==> 1. install updater + config into crafty_container volume"
$SSHC -- "docker exec -i crafty_container sh -c 'mkdir -p /crafty/import/autoupdate/logs'"
$SSHC -- "docker exec -i crafty_container sh -c 'cat > /crafty/import/autoupdate/mc-autoupdate.py'" < "$HERE/mc-autoupdate.py"
# render config from template with secrets/values
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
NEWCOMPOSE=$(apiget "compose.one?composeId=$PLAYIT_COMPOSE" | python3 -c '
import json, sys
c = json.load(sys.stdin); f = c["composeFile"]
f = f.replace("playit-agent:0.17", "playit-agent:1.0")
if "restart:" not in f:
    f = f.replace("network_mode: host", "network_mode: host\n    restart: unless-stopped")
print(json.dumps(f))')
api "compose.update" "{\"composeId\":\"$PLAYIT_COMPOSE\",\"composeFile\":$NEWCOMPOSE}" >/dev/null
echo "    redeploying playit..."
$SSHC -- "curl -fsS -X POST 'http://localhost:3000/api/deploy/compose/$PLAYIT_WEBHOOK'" >/dev/null
echo "    playit updated + redeployed."

echo "==> 3. create/update nightly schedule (3:30 UTC)"
SCRIPT_JSON=$(python3 -c 'import json,sys; print(json.dumps(open(sys.argv[1]).read()))' "$HERE/nightly-maintenance.sh")
EXISTING=$(apiget "schedule.list?id=$ORG&scheduleType=dokploy-server" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(next((s["scheduleId"] for s in d if s["name"] == "mc-nightly-maintenance"), ""))')
if [ -n "$EXISTING" ]; then
  echo "    updating existing schedule $EXISTING"
  api "schedule.update" "{\"scheduleId\":\"$EXISTING\",\"name\":\"mc-nightly-maintenance\",\"cronExpression\":\"30 3 * * *\",\"scheduleType\":\"dokploy-server\",\"shellType\":\"bash\",\"enabled\":true,\"organizationId\":\"$ORG\",\"script\":$SCRIPT_JSON}" >/dev/null
else
  echo "    creating schedule"
  api "schedule.create" "{\"name\":\"mc-nightly-maintenance\",\"cronExpression\":\"30 3 * * *\",\"scheduleType\":\"dokploy-server\",\"shellType\":\"bash\",\"enabled\":true,\"organizationId\":\"$ORG\",\"script\":$SCRIPT_JSON}" >/dev/null
fi
echo "==> done. Manual dry-run:"
echo "    $SSHC -- \"docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py --dry-run\""
