# Runbook — Operational Procedures

Tight, copy-paste procedures for the green-axolotl Minecraft server. For the *why* and the full automation, see [Updates & automation](05-updates-automation.md); for the Bedrock pieces, see [Bedrock connectivity](04-bedrock-connectivity.md).

## Access & API quick reference

```bash
# SSH to the Dokploy host (run all curl commands below from inside this session)
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210
```

| Target | Base | Auth header | Notes |
|---|---|---|---|
| Crafty | `https://localhost:8443/api/v2` | `Authorization: Bearer $CRAFTY_JWT` | self-signed TLS → use `curl -k` |
| Dokploy | `http://localhost:3000/api` | `x-api-key: $DOKPLOY_KEY` | deploy webhooks need no header |

Key IDs: MC server `394a3479-b8e9-4f4f-aa36-49c87eafe548`; crafty container `crafty_container`; playit webhook `FohNmoNN_pzIgkfljoAJo`; crafty webhook `P4G6U5tnpT1UbETaPDfcx`.

> Secrets (`$CRAFTY_JWT`, `$DOKPLOY_KEY`) are placeholders — export them in the SSH session before running; never paste real values.

---

## 1. Restart the MC server

**Crafty UI:** Servers → `mc-paper-1` → **Stop**/**Restart** button.

**API:**

```bash
curl -k -X POST \
  -H "Authorization: Bearer $CRAFTY_JWT" \
  https://localhost:8443/api/v2/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/action/restart_server
```

Confirm it came back: `GET .../servers/<id>/stats` should show `running:true` (see procedure 6).

---

## 2. Backup & restore

### Take a backup

```bash
curl -k -X POST \
  -H "Authorization: Bearer $CRAFTY_JWT" \
  https://localhost:8443/api/v2/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/action/backup_server
```

Backups land in the Crafty volume at `/var/lib/docker/volumes/crafty/backups/`.

### Restore a backup

1. Crafty UI → `mc-paper-1` → **Backups** tab.
2. Pick the backup, click **Restore** (Crafty stops the server, restores, restarts).
3. Verify with procedure 6. To roll back a Paper version too, repoint `executable`/`executable_update_url` — see [rollback in 05](05-updates-automation.md).

---

## 3. Revive playit (tunnel down)

The fix is permanent (image `:1.0` + `restart: unless-stopped`), but to force it back up:

**Deploy webhook:**

```bash
curl -X POST http://localhost:3000/api/deploy/compose/FohNmoNN_pzIgkfljoAJo
```

**Or** Dokploy UI → project **crafty** → compose **playit-agent** → **Redeploy**.

**Verify:**

```bash
docker ps | grep playit                                   # container running?
PID=$(docker ps -q --filter name=playit | head -1)
docker inspect -f '{{.Config.Image}} {{.HostConfig.RestartPolicy.Name}}' "$PID"
```

Expect image ending `playit-agent:1.0` and restart policy `unless-stopped`. If you see `:0.17` or no restart policy, re-run `deploy.sh` (procedure 4) to reapply the compose fix.

---

## 4. Rotate the Crafty JWT or Dokploy key

### Crafty JWT

1. Crafty UI → user/profile → regenerate the API token.
2. Update the JWT in the on-server config (chmod 600 preserved):

   ```bash
   docker exec -i crafty_container sh -c \
     'python3 -c "import json,sys;c=json.load(open(\"/crafty/import/autoupdate/config.json\"));c[\"crafty_jwt\"]=sys.argv[1];json.dump(c,open(\"/crafty/import/autoupdate/config.json\",\"w\"),indent=2)" '"'$CRAFTY_JWT'"
   ```

   Or simplest: re-run the installer with the new value (it re-renders `config.json` from the template):

   ```bash
   cd automation && DOKPLOY_KEY=… CRAFTY_JWT=<new> ./deploy.sh
   ```

### Dokploy API key

1. Dokploy UI → Settings → API/Tokens → regenerate.
2. The Dokploy key is **not** stored on the server — it is only passed to `deploy.sh` via env at install time. Re-run `deploy.sh` with the new `DOKPLOY_KEY` whenever you next need it.

> The nightly orchestrator uses **deploy webhook tokens**, not the API key, so a rotated Dokploy key does not break automation — only manual `deploy.sh`/API calls.

---

## 5. Manually update the Crafty or playit image

The nightly run does this automatically (pull → redeploy only on digest change). To force it now:

```bash
# Crafty
docker pull registry.gitlab.com/crafty-controller/crafty-4:latest
curl -X POST http://localhost:3000/api/deploy/compose/P4G6U5tnpT1UbETaPDfcx

# playit
docker pull ghcr.io/playit-cloud/playit-agent:1.0
curl -X POST http://localhost:3000/api/deploy/compose/FohNmoNN_pzIgkfljoAJo
```

The webhook recreates the container from the freshly pulled image; bind-mount volumes persist. Verify Crafty with procedure 6, playit with procedure 3.

---

## 6. Troubleshooting tree — "players can't connect"

Get server stats up front (used at several steps):

```bash
curl -k -H "Authorization: Bearer $CRAFTY_JWT" \
  https://localhost:8443/api/v2/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/stats
```

Walk the tree top to bottom:

1. **Bedrock or Java?**
   - **Java** clients connect direct to `host:25565` — skip the Geyser/Bedrock checks; jump to step 3.
   - **Bedrock** (Android/console) clients reach the server via the **playit tunnel → host:19132 → Geyser**. Continue.

2. **Is playit up?** `docker ps | grep playit`. If absent/stopped, revive it (procedure 3). No tunnel = no public Bedrock or Java access.

3. **Is the MC server running?** Check `running:true` in the stats above. If not, restart it (procedure 1) and check the Crafty server log for a crash (e.g. a bad jar from the last update).

4. **(Bedrock) Is Geyser current?** A stale Geyser rejects a freshly-updated Bedrock client ("outdated client/server"). Compare installed build to upstream:

   ```bash
   docker exec crafty_container python3 -c \
     'import zipfile,re;print("installed",re.search(r"git.build.number=(\d+)",zipfile.ZipFile("/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/plugins/Geyser-Spigot.jar").read("git.properties").decode()).group(1))'
   ```

   Compare to the latest at `https://download.geysermc.org/v2/projects/geyser/versions/latest/builds/latest`. If installed lags, force an update run (see [05](05-updates-automation.md)). Note the inherent hours-to-days lag right after a Bedrock release — see [Bedrock connectivity](04-bedrock-connectivity.md).

5. **Check the autoupdate log** for the most recent run (did plugins/Paper update or error?):

   ```bash
   docker exec crafty_container sh -c \
     'ls -t /crafty/import/autoupdate/logs/update-*.log | head -1 | xargs tail -n 40'
   ```

   Look for `[error]`/`[warn]` lines or a failed restart. Full automation context in [Updates & automation](05-updates-automation.md).
