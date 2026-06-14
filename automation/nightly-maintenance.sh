#!/bin/bash
# Dokploy dokploy-server schedule body. Runs inside the Dokploy container.
# 1) plugins+paper+restart via the in-Crafty python updater
# 2) pull crafty/playit images, redeploy only when the digest changed
# 3) ensure playit is running
set -uo pipefail
ts() { date -u +%FT%TZ; }
echo "=== mc-nightly-maintenance start: $(ts) ==="

echo "--- step 1: in-Crafty updater ---"
if docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py; then
  echo "[ok] mc-autoupdate completed"
else
  echo "[warn] mc-autoupdate exited non-zero (see /crafty/import/autoupdate/logs)"
fi

update_image() {  # $1=image  $2=webhookToken  $3=label  $4=container-name-filter
  local img="$1" tok="$2" label="$3" cfilter="$4" latest cname running
  if ! docker pull "$img" >/dev/null 2>&1; then echo "[warn] pull failed: $img"; return; fi
  latest=$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null || echo none)
  cname=$(docker ps --filter "name=$cfilter" --format '{{.Names}}' | head -1)
  running=$(docker inspect -f '{{.Image}}' "$cname" 2>/dev/null || echo none)
  if [ "$running" != "$latest" ]; then
    echo "[update] $label running image != latest; redeploying ($running -> $latest)"
    if curl -fsS -X POST "http://localhost:3000/api/deploy/compose/$tok" >/dev/null; then
      echo "[ok] $label redeployed"
    else
      echo "[warn] $label redeploy webhook failed"
    fi
  else
    echo "[ok] $label image already current"
  fi
}

echo "--- step 2: image updates ---"
update_image "registry.gitlab.com/crafty-controller/crafty-4:latest" "P4G6U5tnpT1UbETaPDfcx" "crafty" "crafty_container"
update_image "ghcr.io/playit-cloud/playit-agent:1.0" "FohNmoNN_pzIgkfljoAJo" "playit" "playit"

echo "--- step 3: playit liveness ---"
if docker ps --format '{{.Names}}' | grep -qi playit; then
  echo "[ok] playit container running"
else
  echo "[recover] playit not running; redeploying"
  curl -fsS -X POST "http://localhost:3000/api/deploy/compose/FohNmoNN_pzIgkfljoAJo" >/dev/null \
    && echo "[ok] playit redeploy triggered" || echo "[warn] playit redeploy failed"
fi

echo "=== mc-nightly-maintenance done: $(ts) ==="
