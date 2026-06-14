#!/usr/bin/env bash
# Install a boot-time healer for dokploy-traefik's intermittent overlay-attach race.
# On a cold/ungraceful reboot, dokploy-traefik (standalone, restart=always) sometimes
# fails to re-attach to the dokploy-network overlay ("attaching to network failed:
# context deadline exceeded") from a stale endpoint, and stays down — taking all web
# UIs with it. This installs a systemd oneshot that, ~45s after Docker starts, heals it
# (detach stale endpoint -> start -> reconnect) only if it's not already running.
#
# Run AS ROOT:  sudo bash setup-traefik-heal.sh   (idempotent)
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "ERROR: run with sudo"; exit 1; }

echo "==> 1/4 write /usr/local/sbin/dokploy-traefik-heal.sh"
cat > /usr/local/sbin/dokploy-traefik-heal.sh <<'HEAL'
#!/usr/bin/env bash
# Heal dokploy-traefik if it failed to attach to the dokploy-network overlay.
set -uo pipefail
NET=dokploy-network
C=dokploy-traefik
log(){ echo "[traefik-heal] $(date -u +%FT%TZ) $*"; }

# wait for docker to be responsive
for i in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 2; done

is_running(){ [ "$(docker inspect -f '{{.State.Status}}' "$C" 2>/dev/null)" = "running" ]; }

if ! docker inspect "$C" >/dev/null 2>&1; then
  log "$C does not exist; nothing to heal (Dokploy recreates it)"; exit 0
fi
if is_running; then
  log "$C already running; no heal needed"; exit 0
fi

for a in 1 2 3 4 5; do
  log "heal attempt $a (status=$(docker inspect -f '{{.State.Status}}' "$C" 2>/dev/null))"
  docker network disconnect -f "$NET" "$C" 2>/dev/null || true   # clear stale overlay endpoint
  docker start "$C" >/dev/null 2>&1 || true
  sleep 3
  docker network connect "$NET" "$C" 2>/dev/null || true         # re-attach fresh
  sleep 3
  if is_running; then log "$C is running now"; exit 0; fi
  sleep 10
done
log "FAILED to heal $C after 5 attempts"; exit 1
HEAL
chmod 0755 /usr/local/sbin/dokploy-traefik-heal.sh

echo "==> 2/4 write /etc/systemd/system/dokploy-traefik-heal.service"
cat > /etc/systemd/system/dokploy-traefik-heal.service <<'UNIT'
[Unit]
Description=Heal dokploy-traefik overlay attach after boot
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sleep 45
ExecStart=/usr/local/sbin/dokploy-traefik-heal.sh

[Install]
WantedBy=multi-user.target
UNIT

echo "==> 3/4 enable on boot"
systemctl daemon-reload
systemctl enable dokploy-traefik-heal.service

echo "==> 4/4 one-time check now (no-op if traefik is already up):"
/usr/local/sbin/dokploy-traefik-heal.sh || true

echo
echo "Installed. It runs on every boot and only acts when dokploy-traefik is down."
echo "Logs after a boot:  journalctl -u dokploy-traefik-heal.service"
