# Minecraft Server — Update Automation & Documentation Design

**Date:** 2026-06-14
**Status:** Approved (Approach 1, all steps)
**Author:** Alex + Claude

---

## 1. Problem

A PaperMC server that accepts **Bedrock (Android/console) clients** via Geyser is run through
**Crafty Controller**, deployed on **Dokploy**. Three recurring pain points:

1. **Bedrock clients can't connect after Minecraft updates.** Geyser tracks the Bedrock
   protocol; when Bedrock auto-updates on phones, a stale Geyser build rejects the new client.
   The plugin stack has been frozen since **2026-02-20** (last manual update), so it lags.
2. **playit-agent (the public tunnel) is offline.** The host rebooted 2026-05-30; playit's
   compose has **no restart policy**, so it never came back, and the nightly
   `docker system prune --force` then deleted the stopped container entirely. The server is
   currently reachable **only** by whatever still works (LAN/Tailscale), not the public tunnel.
3. **No upgrade process exists** for Minecraft (Paper), the plugins, playit, or Crafty itself.

**Goal:** a hands-off nightly process that keeps Geyser/Floodgate/Via, Paper, Crafty, and playit
current and the tunnel always up — plus in-depth documentation of the whole setup.

---

## 2. Current-state inventory (discovered 2026-06-14)

### Host & platform
- Dokploy host: homelab VM, LAN `192.168.3.10` behind home NAT (public egress `217.146.109.73`),
  admin via **Tailscale** (`100.65.140.26`; `crafty.tail.keeso.com`, `dokploy.tail.keeso.com`).
- SSH: `ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210`
  (user `alex`, in `docker` group, **no passwordless sudo**).
- Docker 29.5.2. Host booted 2026-05-30 15:54.

### Dokploy
- Version **v0.29.8**, API at `http://localhost:3000/api`, auth header `x-api-key` (REST uses
  **plain query params** for GET, JSON body for POST mutations).
- Organization: `eFbswAqh7vlP_F7SfdS8D`. All services run on the **local** server (`serverId: null`).
- Project **crafty** (`Di61CG06nx38RaT287xRV`, env `8med8lHP8WC2M-OdQhlXW`), two `raw` composes:
  - **ui** (Crafty): composeId `p0FzCTSvUDQkF35o0fd8i`, webhook token `P4G6U5tnpT1UbETaPDfcx`,
    container_name `crafty_container`, image `registry.gitlab.com/crafty-controller/crafty-4:latest`,
    `restart: always`, ports `8123`, `19132/udp`, `25500-25600`.
  - **playit-agent**: composeId `Up4B06-EaIzJuYH3mxgTj`, webhook token `FohNmoNN_pzIgkfljoAJo`,
    image `ghcr.io/playit-cloud/playit-agent:0.17`, `network_mode: host`, `SECRET_KEY` set,
    **no restart policy**, container currently **absent**.
- Existing `dokploy-server` schedule: **"Daily Docker Cleanup at 3am"** (`0 3 * * *`,
  script `docker system prune --force`).

### Crafty Controller
- Version **4.9.0** (latest is 4.10.4; `:latest` tag, so a redeploy pulls newest).
- API base `https://localhost:8443/api/v2` (self-signed TLS), auth `Authorization: Bearer <JWT>`.
- Manages one server inside its own container (Java child process).
- Useful endpoints: `PATCH /servers/{id}` (edit `executable`, `execution_command`,
  `executable_update_url`); `POST /servers/{id}/action/{backup_server|restart_server|
  stop_server|start_server|update_executable}`; `POST /servers/{id}/stdin` (console, no leading `/`);
  `POST /servers/{id}/tasks` (internal cron); file API under `/servers/{id}/files/...`.
- Volumes (host bind mounts, persist across container recreation):
  `/var/lib/docker/volumes/crafty/{config,backups,import,logs,servers}`.

### Minecraft server (`mc-paper-1`, `394a3479-b8e9-4f4f-aa36-49c87eafe548`)
- **Paper 1.21.8** (`paper-1.21.8.jar`), `java -Xms1000M -Xmx2000M`, Java 25 in-container.
- `executable_update_url`: `https://jars.arcadiatech.org/paper/1.21.8/paper.jar` (Crafty mirror).
- `server-port=25565`, `online-mode=true` (Bedrock bypasses via Floodgate), gamemode creative.
- Container has **python3 only** — no curl/wget/unzip. Has outbound internet.
- **Active plugins** (last updated 2026-02-20): `Geyser-Spigot.jar`, `floodgate-spigot.jar`,
  `ViaVersion-5.7.1.jar`, `ViaBackwards-5.7.1.jar`, `MyCommand.jar`.
- **Orphaned data** (no jar; cleanup candidates): `Essentials/`, `Updater/` (dormant Bukkit
  updater-lib config), `old_plugins_backup/` (Feb-20 backup: Via 5.5.0, old Geyser/Floodgate).
  `spark/` is Paper-bundled. `.paper-remapped/` is Paper's cache.

### green-axolotl customization
- Signature command `/greenaxolotl` (MyCommand `commands.yml`): gives a green axolotl spawn egg
  (`Variant:4`), 300s cooldown, no permission required.
- **Bedrock resource pack** "Green Axolotl Pack" (`green-axolotl-pack-br.mcpack`,
  uuid `2d0e25e1-4630-4349-9923-e52792e38b6d`, v0.0.1) — re-textures the rare blue axolotl green.
  Served automatically to Bedrock clients from `plugins/Geyser-Spigot/packs/`.
  Copied to repo `green-axolotl/green-axolotl-pack-br.mcpack` (canonical).
- Repo's `green-axolotl/pack.zip` is a stale **Java** resource-pack experiment (superseded).

### Current latest upstream versions (2026-06-14)
- Geyser **2.10.1 build 1165**; Floodgate **2.2.5 build 132**; ViaVersion/ViaBackwards **5.9.1**.
- Paper: latest stable MC **26.1.2**; 1.21.8 latest build **60**. **PaperMC v2 API shuts down
  2026-07-01 → must use Fill v3 (`fill.papermc.io/v3`).**
- playit-agent **1.0.10** (`:1.0` rolling tag recommended; `:0.17` deprecated).
- Crafty **4.10.4** (4.10.3 carried a security fix).

---

## 3. Goals / non-goals

**Goals**
- Daily, hands-off updates of Geyser, Floodgate, ViaVersion, ViaBackwards.
- Daily Paper updates riding the **latest stable** Minecraft version (with pre-update backup).
- Keep Crafty and playit images current (pull + redeploy only when the image changes).
- playit **always running** (survives reboots and prune).
- Nightly MC-server restart (memory hygiene + load new jars).
- Log every run; recoverable on failure.
- In-depth documentation of the whole stack and the upgrade process.

**Non-goals**
- No external notification service (log-file only, per decision).
- No migration off Crafty/Dokploy.
- No automatic adoption of release-candidate/experimental Paper builds.
- Not touching world gameplay/config beyond what updates require.

---

## 4. Approved design (Approach 1)

### 4.1 Durable liveness fix (one-time, not a schedule)
Edit the **playit** compose `composeFile` via Dokploy `compose.update`:
- image `ghcr.io/playit-cloud/playit-agent:0.17` → **`:1.0`**
- add **`restart: unless-stopped`**
Then redeploy (webhook `FohNmoNN_pzIgkfljoAJo`). This guarantees playit returns after any
reboot/exit and is never left stopped for prune to delete.

### 4.2 One nightly schedule — `mc-nightly-maintenance`
- Dokploy **`dokploy-server`** schedule, `shellType: bash`, cron **`30 3 * * *`** (3:30 AM UTC,
  after the 3:00 prune), `organizationId: eFbswAqh7vlP_F7SfdS8D`, `enabled: true`.
- Created via `POST /api/schedule.create`. The `script` field holds the orchestrator below.
- The orchestrator runs **inside the Dokploy container** (has docker socket, curl, node, docker CLI).

**Orchestrator steps (`nightly-maintenance.sh`):**
1. `docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py`
   → updates plugins + Paper, backs up + restarts the MC server (see 4.3). All its logs flow to
   stdout (captured in Dokploy's schedule run history) **and** a dated file in the Crafty volume.
2. **Image updates** for Crafty and playit: for each `(image, webhookToken)`:
   - `old=$(docker image inspect -f '{{.Id}}' <image>)`; `docker pull <image>`;
     `new=$(docker image inspect -f '{{.Id}}' <image>)`.
   - If `old != new`: `curl -X POST http://localhost:3000/api/deploy/compose/<webhookToken>`
     (redeploys, recreating the container from the freshly pulled image; volumes persist).
3. **playit safety net**: if no container matches `name=playit`, redeploy via its webhook.
4. Emit a run summary line.

### 4.3 In-Crafty updater — `mc-autoupdate.py`
Pure-`python3` (stdlib `urllib`, `ssl`, `zipfile`, `hashlib`, `json`). Lives in the persistent
Crafty volume at `/crafty/import/autoupdate/`. Reads secrets from a sibling perms-restricted
`config.json` (Crafty JWT, server_id, paths, tunables) — never hardcoded.

Logic, in order, each gated so nothing happens unless something is genuinely newer:

- **Plugins** (`plugins/`):
  - *Geyser, Floodgate* — read installed `git.build.number` from the jar (`zipfile` → `git.properties`);
    GET `https://download.geysermc.org/v2/projects/{geyser|floodgate}/versions/latest/builds/latest`
    (urllib follows the 302); if `latest.build > installed`, download
    `.../downloads/spigot` to a temp file, verify it's a valid zip/jar, atomically replace.
  - *ViaVersion, ViaBackwards* — read installed version from `plugin.yml` in the jar; GET
    `https://api.github.com/repos/ViaVersion/{ViaVersion|ViaBackwards}/releases/latest`; if the
    release tag is newer, download the `.jar` asset (`browser_download_url`), replace, and remove
    the old versioned jar.
  - Track whether any plugin changed (`plugins_changed`).
- **Paper** (ride latest **stable** MC):
  - GET `https://fill.papermc.io/v3/projects/paper` → highest **stable** MC version `V`.
  - GET `https://fill.papermc.io/v3/projects/paper/versions/{V}/builds` → latest stable build `B`
    and its `downloads.server:default.url` (+ sha256).
  - Compare `(V, B)` to the running jar (parsed from the server's `execution_command`/`executable`).
    If newer: **backup first** (`POST /action/backup_server`), download the jar to a canonical
    `paper.jar` in the server dir (verify sha256), `PATCH /servers/{id}` to set
    `executable=paper.jar`, `execution_command=java -Xms1000M -Xmx2000M -jar paper.jar nogui`,
    `executable_update_url=<that v3 url>`. Mark `paper_changed`.
  - Config knob `mc_version_min_age_days` (default `0` per decision; can be raised to soak new
    majors) — skip a target version newer than the threshold.
- **Restart**: always issue `POST /servers/{id}/action/restart_server` (nightly hygiene; also
  loads any replaced jars). On failure, retry once, then log an error (non-zero exit).
- **Logging**: structured lines (timestamp, component, from→to, action) to stdout and
  `/crafty/import/autoupdate/logs/update-YYYY-MM-DD.log` (rotation: keep last 30).

All Crafty API calls go to `https://localhost:8443` with an unverified SSL context (self-signed)
and `Authorization: Bearer <JWT>`.

### 4.4 Secrets & config
`/crafty/import/autoupdate/config.json` (chmod 600), fields: `crafty_base`
(`https://localhost:8443`), `crafty_jwt`, `server_id`, `server_dir`, `plugins_dir`,
`mc_version_min_age_days`, `keep_logs`. The Dokploy `compose.update`/webhook calls in the
orchestrator use the **deploy webhook tokens** (no API key embedded). Where the Dokploy API key is
needed (initial setup only), it is passed to `deploy.sh` via env, not stored on the server.

### 4.5 Idempotent installer — `deploy.sh` (run from the local repo)
Run once from the workstation; safe to re-run. Steps:
1. Push `mc-autoupdate.py` + `config.json` into `crafty_container:/crafty/import/autoupdate/`
   (stream over SSH; `chmod 600` config). Create `logs/`.
2. Fix the playit compose: `compose.update` (image `:1.0` + `restart: unless-stopped`), redeploy.
3. Create/update the `mc-nightly-maintenance` schedule: `schedule.list?id=<org>&scheduleType=
   dokploy-server`; if a schedule with our name exists, `schedule.update` it, else
   `schedule.create`. Embed `nightly-maintenance.sh` as the `script`.
4. Smoke test: `schedule.runManually` (or run the orchestrator once) and tail the logs.

Canonical copies of all three scripts live in the repo under `automation/`.

---

## 5. Documentation deliverable (committed to repo)

```
README.md                      overview + index + "I just want to…" quick links
docs/
  01-architecture.md           Dokploy host, Tailscale, NAT/playit path, Traefik, all containers
  02-minecraft-server.md       Paper, the 5 plugins, configs, ports, Crafty server settings
  03-green-axolotl.md          the .mcpack + /greenaxolotl + how Geyser serves it + updating the pack
  04-bedrock-connectivity.md   Geyser/Floodgate/Via, how Android clients connect, the protocol-lag problem
  05-updates-automation.md     THE upgrade guide: what updates how, schedule, scripts, manual ops, rollback
  06-runbook.md                restart, restore backup, revive playit, rotate keys, "can't connect" triage
automation/
  mc-autoupdate.py             in-Crafty updater (plugins + Paper)
  nightly-maintenance.sh       the dokploy-server orchestrator (steps 1–4 of §4.2)
  config.example.json          template (no secrets)
  deploy.sh                    idempotent installer (§4.5)
green-axolotl/
  green-axolotl-pack-br.mcpack canonical Bedrock pack (done)
  pack.zip                     stale Java experiment (documented as such)
```

---

## 6. Risks & mitigations

- **MC major-version jump breaks plugins/world.** Mitigation: plugins update *before* Paper in
  the same run (latest Geyser/Via in place); **stable-only**; **backup before every Paper change**;
  `mc_version_min_age_days` soak knob; documented rollback (restore backup + repoint
  `executable`/`executable_update_url` to the prior version, redeploy/restart).
- **3 AM prune race.** Mitigation: maintenance at **3:30** (after the 3:00 prune); playit gets a
  restart policy so it's never a stopped-container prune target.
- **Dokploy redeploy doesn't pull `image:` tags.** Mitigation: orchestrator does an explicit
  `docker pull` first, then redeploys only on digest change.
- **Geyser build lag after a Bedrock release.** Inherent (hours–days); daily runs minimize it.
  Cannot be fully eliminated.
- **Self-signed Crafty TLS.** Mitigation: unverified SSL context for `localhost:8443` only.
- **PaperMC v2 EOL 2026-07-01.** Mitigation: use Fill **v3** from day one.
- **Secrets at rest.** Mitigation: `config.json` chmod 600 in a root-owned volume; redeploys use
  webhook tokens, not the API key.

---

## 7. Open questions
None blocking. Default `mc_version_min_age_days=0` per the "ride latest" decision; revisit if a
bad major jump occurs.
