# 05 — Updates & Automation (the upgrade guide)

This is the doc to read before touching anything that updates. It explains exactly **what** keeps the green-axolotl Minecraft server current (Geyser/Floodgate, ViaVersion/ViaBackwards, Paper, Crafty, playit), **how** the nightly automation does it, and the **manual** force-run / dry-run / rollback procedures. For day-to-day "it broke, fix it now" steps see the [runbook](06-runbook.md); for why Bedrock clients lag after a Minecraft update see [Bedrock connectivity](04-bedrock-connectivity.md).

> **SSH into the host** for every manual command below:
>
> ```bash
> ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210
> ```
>
> You land as `alex` (in the `docker` group, no passwordless sudo). The Dokploy API is reachable from there at `http://localhost:3000/api`; the Crafty API at `https://localhost:8443/api/v2` (self-signed TLS).

---

## 1. Architecture at a glance

Everything hangs off **one** Dokploy `dokploy-server` schedule:

| Field | Value |
|---|---|
| Name | `mc-nightly-maintenance` |
| Cron | `30 3 * * *` (**3:30 AM UTC**) |
| Shell | `bash` |
| Type | `dokploy-server` (runs **inside the Dokploy container** — has the docker socket, `curl`, `node`, docker CLI) |
| Org | `eFbswAqh7vlP_F7SfdS8D` |
| Enabled | `true` |

**Why 3:30 and not 3:00?** There is an existing `dokploy-server` schedule, **"Daily Docker Cleanup at 3am"** (`0 3 * * *`, body `docker system prune --force`). Our maintenance is deliberately set **after** it (3:30) so that:

1. the prune isn't deleting images/containers mid-update, and
2. anything our run pulls/redeploys is fresh and won't be pruned out from under a stopped container before the next cycle.

There are **two actors**, and the split matters:

```
Dokploy schedule (3:30 UTC)
   └── nightly-maintenance.sh         ← ORCHESTRATOR, runs in the Dokploy container
         ├── docker exec crafty_container python3 …/mc-autoupdate.py
         │        └── mc-autoupdate.py ← UPDATER, runs INSIDE crafty_container
         │              • plugins (Geyser/Floodgate/Via) + Paper
         │              • backup-before-Paper, restart server
         │              • talks to the Crafty API on https://localhost:8443
         ├── docker pull crafty image  → redeploy webhook only if digest changed
         ├── docker pull playit image   → redeploy webhook only if digest changed
         └── playit liveness net: redeploy if no playit container is running
```

- **`nightly-maintenance.sh`** (orchestrator) — bash, lives as the schedule's `script` body in Dokploy. It has docker + curl, so it owns image pulls, deploy-webhook redeploys, and the playit safety net. Canonical copy: [`automation/nightly-maintenance.sh`](../automation/nightly-maintenance.sh).
- **`mc-autoupdate.py`** (updater) — **pure `python3` stdlib only** (`urllib`, `ssl`, `zipfile`, `hashlib`, `json`), because `crafty_container` has python3 but **no curl/wget/unzip**. It lives in the persistent Crafty volume at `/crafty/import/autoupdate/` and updates the plugins + Paper jar and restarts the server via the Crafty API. Canonical copy: [`automation/mc-autoupdate.py`](../automation/mc-autoupdate.py).

---

## 2. What updates, and how

Each component has a different "is there something newer?" gate. Nothing is touched unless something is genuinely newer (image redeploys are digest-gated; plugin/Paper swaps are version-gated).

| Component | Source / API | Gate | Mechanism |
|---|---|---|---|
| **Geyser** (`Geyser-Spigot.jar`) | GeyserMC download API: `https://download.geysermc.org/v2/projects/geyser/versions/latest/builds/latest` | **Build number** — installed `git.build.number` (read from `git.properties` in the jar) vs `latest.build` | Download `…/downloads/spigot`, verify it's a valid zip/jar, atomically replace in `plugins/` |
| **Floodgate** (`floodgate-spigot.jar`) | Same API, `projects/floodgate` | Build number (same as Geyser) | Same — download `…/downloads/spigot`, atomic replace |
| **ViaVersion** (`ViaVersion-*.jar`) | GitHub `https://api.github.com/repos/ViaVersion/ViaVersion/releases/latest` | **Semver** — installed `version:` from `plugin.yml` vs the release tag | Download the `.jar` asset (`browser_download_url`) as `ViaVersion-<tag>.jar`, then **delete the old versioned jar** |
| **ViaBackwards** (`ViaBackwards-*.jar`) | GitHub `…/repos/ViaVersion/ViaBackwards/releases/latest` | Semver (same) | Same — download new versioned jar, remove old |
| **Paper** (`paper.jar`) | PaperMC **Fill v3** — `https://fill.papermc.io/v3/projects/paper` then `…/versions/{V}/builds`. **v2 API is retired (EOL 2026-07-01) — Fill v3 only.** | Latest **STABLE** MC version `V` + its newest stable build `B`, compared to running `(version, build)` | **Backup first** via Crafty, download server jar to canonical `paper.jar` (verify **sha256**), then `PATCH /servers/{id}` to set `executable`, `execution_command`, `executable_update_url` |
| **Crafty image** | `registry.gitlab.com/crafty-controller/crafty-4:latest` | **Image digest** changed | `docker pull`; if `.Id` changed, redeploy via Dokploy webhook `P4G6U5tnpT1UbETaPDfcx` (recreates container; volumes persist) |
| **playit image** | `ghcr.io/playit-cloud/playit-agent:1.0` | **Image digest** changed | `docker pull`; if `.Id` changed, redeploy via Dokploy webhook `FohNmoNN_pzIgkfljoAJo` |

**Update order within a run is intentional:** plugins update **before** Paper, so the newest Geyser/Floodgate/Via are already in place when Paper rides up to a newer Minecraft version. The MC server is restarted **once** at the end (nightly memory hygiene + loads any swapped jars).

### Paper specifics

- The jar is swapped to a **canonical `paper.jar`** (not a versioned filename), so `executable` never has to change name-to-name. After download, the updater issues:
  - `PATCH /servers/394a3479-b8e9-4f4f-aa36-49c87eafe548` with `executable=paper.jar`, `execution_command=java -Xms1000M -Xmx2000M -jar paper.jar nogui`, and `executable_update_url=<the Fill v3 download URL>`.
- **Backup-before-change:** before writing the new jar, the updater calls `POST /servers/{id}/action/backup_server`. That backup is your rollback point (see §6).
- Only **STABLE** (or RECOMMENDED) channel builds are eligible — no release-candidate/experimental Paper.

### Crafty / playit images

Dokploy's redeploy does **not** itself pull `image:` tags, so the orchestrator does an explicit `docker pull` first and only fires the deploy webhook when the resolved image `.Id` actually changed. This keeps redeploys (and the container churn they cause) down to runs where there's a real new image.

---

## 3. The `mc-autoupdate.py` flow (per component)

In order, each step gated:

1. **Plugins** (`update_plugins`):
   - Geyser, Floodgate — `update_one_geyser`: read installed build from the jar, GET the GeyserMC latest-build JSON; if `latest.build > installed`, download `…/downloads/spigot`, validate zip, atomic replace.
   - ViaVersion, ViaBackwards — `update_one_via`: read installed `plugin.yml` version, GET the GitHub latest release; if the tag is newer (`semver_newer`), download the `.jar` asset and remove the old versioned jar.
2. **Paper** (`update_paper`): `find_latest_paper` walks Fill v3 (highest STABLE MC version first, `select_stable_build` picks the newest stable build old enough); `_paper_newer` compares to the tracked state; if newer → backup, download+verify, `PATCH`, persist new state.
3. **Restart** (`restart_server`): always issued at the end unless `--dry-run`. On failure it retries once, then logs an error and the process exits non-zero (so the orchestrator flags it).

State lives in `/crafty/import/autoupdate/state.json` (`{"paper": {"version": …, "build": …}}`). On first run it's bootstrapped from the server's current `executable` filename via the Crafty API (`build: 0` forces a refresh to the latest stable).

All Crafty calls go to `https://localhost:8443` with an **unverified SSL context** (self-signed cert, localhost only) and `Authorization: Bearer <Crafty JWT>`.

---

## 4. `config.json` (secrets + tunables)

Lives at **`/crafty/import/autoupdate/config.json`**, **`chmod 600`**, in a root-owned volume. It holds the **Crafty JWT**, so it is **gitignored** — the repo only ever contains the no-secrets template [`automation/config.example.json`](../automation/config.example.json). Fields:

| Field | Purpose |
|---|---|
| `crafty_base` | `https://localhost:8443` |
| `crafty_jwt` | **Secret.** Crafty Controller API bearer token (referred to as the **Crafty JWT** everywhere in these docs) |
| `server_id` | `394a3479-b8e9-4f4f-aa36-49c87eafe548` |
| `server_dir` | `/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548` |
| `plugins_dir` | `…/394a3479-…/plugins` |
| `autoupdate_dir` | `/crafty/import/autoupdate` (logs + state live here) |
| `jvm_args` | `-Xms1000M -Xmx2000M` (used to rebuild `execution_command` on a Paper swap) |
| `paper_canonical_jar` | `paper.jar` |
| **`mc_version_min_age_days`** | **The soak knob.** Skip any MC build newer than this many days. Default `0` = "ride latest stable". Raise it (e.g. `7`, `14`) to let a new major version season before adopting it. |
| `keep_logs` | How many dated log files to retain (default `30`) |
| `update_plugins` | Toggle: update Geyser/Floodgate/Via at all (default `true`) |
| `update_paper` | Toggle: update Paper at all (default `true`) |
| `restart` | Toggle: restart the server at the end of a run (default `true`) |

> The Crafty JWT is the **only** secret in `config.json`. The orchestrator's Dokploy redeploys use **deploy-webhook tokens** (not the API key), so no Dokploy API key is stored on the server. The Dokploy API key is needed **only at install time** and is passed to `deploy.sh` via env (see §7).

---

## 5. Where the logs live

Two places, both worth knowing:

1. **In the Crafty volume** — the updater writes a dated file per run:
   - `/crafty/import/autoupdate/logs/update-YYYY-MM-DD.log` (kept for `keep_logs` days).
   - Read the latest from your workstation:
     ```bash
     ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
       'docker exec crafty_container sh -c "tail -n 80 /crafty/import/autoupdate/logs/update-$(date -u +%F).log"'
     ```
   - Lines are structured: `<UTC timestamp> [ok|update|backup|restart|error] <component>: <from -> to / action>`.
2. **The Dokploy schedule run history** — the orchestrator's stdout (including the updater's stdout, the image-pull/redeploy lines, and the playit liveness check) is captured per run. Open the `mc-nightly-maintenance` schedule in the Dokploy UI and read its run output, or query the API.

---

## 6. Manual procedures

All of these use the SSH pattern at the top of this doc. They're copy-paste safe.

### Force a run now (apply updates + restart)

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  'docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py'
```

This runs only the **updater** (plugins + Paper + restart). To force the **whole** orchestrator (updater **and** image pulls + playit check), trigger the schedule instead:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  "curl -fsS -X POST 'http://localhost:3000/api/schedule.runManually' \
   -H 'x-api-key: \$DOKPLOY_KEY' -H 'Content-Type: application/json' \
   -d '{\"scheduleId\":\"<scheduleId>\"}'"
```

(Get `<scheduleId>` from `schedule.list?id=eFbswAqh7vlP_F7SfdS8D&scheduleType=dokploy-server`.)

### Dry-run (decide nothing, change nothing)

Shows what *would* update — no downloads, no PATCH, no restart:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  'docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py --dry-run'
```

Expect lines like `[update] geyser: 1100 -> 1165`, `[update] ViaVersion: 5.7.1 -> 5.9.1`, a Paper line, and `done (changed=True, errors=0)`.

### Change the cadence (cron) or the soak window

**Cadence** lives in the Dokploy schedule's `cronExpression`. Edit it in the Dokploy UI (Schedules → `mc-nightly-maintenance`), or via the API — keep it **after** the 3:00 prune:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  "curl -fsS -X POST 'http://localhost:3000/api/schedule.update' \
   -H 'x-api-key: \$DOKPLOY_KEY' -H 'Content-Type: application/json' \
   -d '{\"scheduleId\":\"<scheduleId>\",\"cronExpression\":\"30 3 * * *\"}'"
```

**Soak window** (how long a new MC major must season before adoption) lives in `mc_version_min_age_days` in `config.json`. To raise it to, say, 14 days:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  'docker exec crafty_container python3 - <<PY
import json
p="/crafty/import/autoupdate/config.json"
c=json.load(open(p)); c["mc_version_min_age_days"]=14
json.dump(c, open(p,"w"), indent=2)
print("min_age_days =", c["mc_version_min_age_days"])
PY'
```

The same approach flips `update_paper`/`update_plugins`/`restart` toggles. To re-pin permanently, also update [`automation/config.example.json`](../automation/config.example.json) in the repo so a future `deploy.sh` re-render keeps your value.

### Re-run the installer (`deploy.sh`)

`deploy.sh` is idempotent — re-run it any time you change `mc-autoupdate.py`, `nightly-maintenance.sh`, or `config.example.json`. It re-pushes the updater + re-renders `config.json` (chmod 600), re-applies the playit compose fix, and creates-or-updates the schedule. It needs **two secrets in the environment** — the Dokploy API key and the Crafty JWT — and nothing else (it embeds the SSH target):

```bash
cd /home/alex/mc-stuff/automation
DOKPLOY_KEY=… CRAFTY_JWT=… ./deploy.sh
```

> Never paste these into a committed file or your shell history. `deploy.sh` reads `$DOKPLOY_KEY` / `$CRAFTY_JWT` from env only; the rendered `config.json` lands on the server `chmod 600`.

---

## 7. Rollback

Three independent rollback paths, by what broke.

### A. A Paper update broke the world / server won't start → restore a Crafty backup

Every Paper change is preceded by an automatic backup (`backup_server`). Restore the most recent good one:

- **Crafty UI:** open `mc-paper-1` → **Backups** → pick the pre-update backup → **Restore**.
- **API:** Crafty exposes backup management under the server's API; the simplest path is the UI. Backups persist on the host bind mount under `/var/lib/docker/volumes/crafty/backups/…`, so they survive container recreation.

### B. Roll Paper back to a prior version (jar + Crafty pointers)

Repoint the server to a known-good Paper build with `PATCH /servers/{id}` (the inverse of what the updater does on the way up). Set `executable_update_url` to the prior version's Fill v3 download URL and let Crafty's `update_executable` action re-fetch it, **or** drop a known-good jar in place and point `executable` at it:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  "curl -fsSk -X PATCH 'https://localhost:8443/api/v2/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548' \
   -H 'Authorization: Bearer \$CRAFTY_JWT' -H 'Content-Type: application/json' \
   -d '{\"executable\":\"paper.jar\",
        \"execution_command\":\"java -Xms1000M -Xmx2000M -jar paper.jar nogui\",
        \"executable_update_url\":\"https://jars.arcadiatech.org/paper/1.21.8/paper.jar\"}'"
```

Then `POST …/action/update_executable` (re-download from `executable_update_url`) and `…/action/restart_server`. Also update `state.json` (`paper.version`/`paper.build`) to the version you rolled back to, or the next nightly run will immediately re-upgrade you. To **stop** auto-upgrades while you investigate, set `update_paper: false` in `config.json` (§6).

### C. Roll a plugin back from the Feb-20 backup

A pre-existing backup of the old plugin set lives at `plugins/old_plugins_backup/` (the 2026-02-20 freeze: ViaVersion 5.5.0, older Geyser/Floodgate). Restore one jar by copying it back over the active one and restarting:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  'docker exec crafty_container sh -c "
   P=/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/plugins
   cp \$P/old_plugins_backup/ViaVersion-5.5.0.jar \$P/ &&
   rm -f \$P/ViaVersion-5.9.1.jar"'
```

Then restart the server (Crafty UI or `…/action/restart_server`). To keep the nightly run from re-upgrading it, set `update_plugins: false` while you investigate.

---

## 8. The playit fix (and why it mattered)

playit-agent is the public tunnel (Bedrock phone → playit → host `:19132` → Geyser → Paper). It went **dark** and the failure was a chain:

1. The playit compose had **no restart policy**.
2. The host **rebooted** (2026-05-30) — the stopped container never came back.
3. The 3:00 nightly `docker system prune --force` then **deleted the stopped container** entirely.

So the server was reachable only over LAN/Tailscale, not the public tunnel. The durable fix (applied once by `deploy.sh`, §4.1 of the design) is a two-part compose change to the playit service (compose `Up4B06-EaIzJuYH3mxgTj`):

- image `ghcr.io/playit-cloud/playit-agent:0.17` → **`:1.0`** (`:0.17` is deprecated; `:1.0` is the recommended rolling tag).
- add **`restart: unless-stopped`**.

With a restart policy, playit comes back after any reboot/exit and is **never left stopped** for the prune to delete. The orchestrator also keeps a belt-and-suspenders **liveness net**: step 3 of `nightly-maintenance.sh` redeploys playit (webhook `FohNmoNN_pzIgkfljoAJo`) if no container named `playit` is running at run time.

The `SECRET_KEY` env (referred to by name only — never print it) on the playit compose is unchanged by the fix.

---

## 9. See also

- [04 — Bedrock connectivity](04-bedrock-connectivity.md) — why Bedrock/Android clients can't connect after a Minecraft update, and how keeping Geyser current fixes it.
- [06 — Runbook](06-runbook.md) — fast, task-oriented procedures: restart the server, restore a backup, revive playit, rotate the Crafty JWT / Dokploy key, and the "players can't connect" triage tree.
