# Deployment log — 2026-06-14 (initial rollout)

First live deployment of the update automation. Recorded here because several
issues surfaced and were fixed during rollout (and the world was migrated).

## Outcome (all verified live)

| Component | Before | After |
|---|---|---|
| playit-agent | down (no restart policy, pruned) | **running on `:1.0`, `restart: unless-stopped`** |
| Geyser | build 1077 (2.9.4) | **1165 (2.10.1)** |
| Floodgate | b127 | **b132 (2.2.5)** |
| ViaVersion / ViaBackwards | 5.7.1 | **5.9.1** |
| Paper / Minecraft | 1.21.8 | **26.1.2 build 69** (world migrated to 26.x) |
| Crafty Controller | 4.9.0 | **4.10.4** |
| Nightly schedule | none | **`mc-nightly-maintenance` @ `30 3 * * *` UTC** (proven via manual run) |

The server boots cleanly on Paper 26.1.2 (Java 25), Geyser is listening on UDP
19132, all 5 plugins load.

## Issues found & fixed during rollout

1. **Dokploy schedule API** rejected create without a `command` field even for
   `dokploy-server` type — added `command: ""`.
2. **PaperMC Fill v3 `versions`** is a dict keyed by version-group, not a flat
   list — `find_latest_paper` was 404ing. Fixed to flatten + skip pre-releases.
3. **Java-minimum guard** added — the updater now refuses to adopt a Paper
   version whose Java minimum exceeds the container JVM (25), so a future major
   jump can't leave the server unstartable.
4. **CRITICAL — jar permissions.** `http_download` used `mkstemp` (0600,
   root-owned). The server runs as the `crafty` user and could not read the new
   jar, so the post-update start silently failed (no Java process, nothing in
   `latest.log`). Fixed: `chmod 0644` after download. The already-deployed jars
   were `chown`ed to `crafty` and `chmod 644` to recover.
5. **Floodgate build detection** — Floodgate has no `git.properties`; its build
   is the `b<NN>` in the plugin.yml version. Added that fallback so it isn't
   re-downloaded every night.
6. **Image-update comparison** — the orchestrator compared the local image
   before/after pull; corrected to compare the running container's image vs the
   latest image (so an already-pulled update is still applied).

## Rollback point (kept on the server)

`/crafty/import/autoupdate/rollback/` on the host (in the Crafty volume):
- `pre26-world.tgz` — the pre-migration 1.21.8 world (world/nether/end + configs).
- `PRIOR-STATE.txt` — the prior `executable` / `execution_command` (paper-1.21.8.jar).
- `paper-1.21.8.jar` is still present in the server dir.

To roll back to 1.21.8: stop the server, restore the world from `pre26-world.tgz`,
`PATCH /servers/{id}` `executable=paper-1.21.8.jar` (+ matching
`execution_command`), set `state.json` `paper` to `1.21.8`, set
`update_paper:false` in `config.json`, start. See [05-updates-automation.md](05-updates-automation.md) §7.

## Note on the docs

`docs/01–06` and the spec describe the *mechanism* and the discovery-time
baseline (Paper 1.21.8 / Crafty 4.9.0). Live versions are now 26.1.2 / 4.10.4 —
the automation keeps them current from here.
