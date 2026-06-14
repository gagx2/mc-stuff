# green-axolotl Minecraft server

Documentation, the canonical Bedrock resource pack, and the nightly update automation for the **green-axolotl** Minecraft server.

This is a **PaperMC 1.21.8** server with **Bedrock (Android/console) support** via **Geyser + Floodgate**, managed by **Crafty Controller** running on **Dokploy**. A single nightly schedule keeps Geyser/Floodgate/ViaVersion/ViaBackwards, Paper, Crafty, and the playit tunnel current — so Android/Bedrock players keep connecting after Minecraft auto-updates their clients — and guarantees the public tunnel stays up across reboots.

## I just want to…

| I want to… | Go to |
| --- | --- |
| Understand the whole stack (host, Dokploy, Tailscale, NAT, containers, the Bedrock path) | [docs/01-architecture.md](docs/01-architecture.md) |
| Know the server, Paper version, plugins, ports, and Crafty settings | [docs/02-minecraft-server.md](docs/02-minecraft-server.md) |
| Work on the green-axolotl pack and the `/greenaxolotl` command | [docs/03-green-axolotl.md](docs/03-green-axolotl.md) |
| Fix "Bedrock/Android players can't connect" / understand the protocol lag | [docs/04-bedrock-connectivity.md](docs/04-bedrock-connectivity.md) |
| Read the upgrade guide: what updates, the schedule, scripts, manual ops, rollback | [docs/05-updates-automation.md](docs/05-updates-automation.md) |
| Run an ops procedure: restart, restore a backup, revive playit, rotate keys, triage | [docs/06-runbook.md](docs/06-runbook.md) |
| Understand VM OS auto-updates + reboot resilience (the Ubuntu/Proxmox layer) | [docs/07-vm-os-updates.md](docs/07-vm-os-updates.md) |

## Architecture in one paragraph

Crafty Controller (`:latest`, `crafty_container`) runs the Paper 1.21.8 server (`mc-paper-1`, id `394a3479-b8e9-4f4f-aa36-49c87eafe548`) as an in-container Java process on `server-port=25565` with `online-mode=true` (Bedrock bypasses auth via Floodgate). Bedrock phones reach it over the **playit** public tunnel into the host's `19132/udp`, where **Geyser** translates the Bedrock protocol into Java and **ViaVersion/ViaBackwards** bridge version gaps. Both Crafty and playit are Dokploy `raw` composes in the **crafty** project (`Di61CG06nx38RaT287xRV`). Every night at **3:30 AM UTC** (after the 3:00 Docker prune) the `mc-nightly-maintenance` Dokploy `dokploy-server` schedule runs `nightly-maintenance.sh`, which (1) `docker exec`s the in-Crafty `mc-autoupdate.py` to update the four plugins + Paper (backup before any Paper change) and restart the server, (2) pulls the Crafty and playit images and redeploys via deploy-webhooks only when the digest changed, and (3) makes sure playit is running. The playit compose was pinned to `ghcr.io/playit-cloud/playit-agent:1.0` with `restart: unless-stopped` so the tunnel always survives reboots and the nightly prune.

## Update automation (`automation/`)

The canonical copies of all automation scripts live here; `deploy.sh` installs the updater into the persistent Crafty volume and creates the schedule. See [docs/05-updates-automation.md](docs/05-updates-automation.md) for the full guide.

| File | Role |
| --- | --- |
| `automation/mc-autoupdate.py` | In-Crafty updater (Python stdlib only). Updates plugins + Paper, backs up, restarts via the Crafty API. |
| `automation/nightly-maintenance.sh` | The `dokploy-server` orchestrator (updater + image pull/redeploy + playit liveness). |
| `automation/config.example.json` | Config template — no secrets. Real `config.json` lives on the server (chmod 600). |
| `automation/deploy.sh` | Idempotent installer; run once from the workstation. |
| `automation/tests/` | pytest unit tests for the updater (dev only). |

```bash
# SSH to the host
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210

# Install / re-run the installer (secrets via env — never committed)
cd automation && DOKPLOY_KEY=$DOKPLOY_KEY CRAFTY_JWT=$CRAFTY_JWT ./deploy.sh

# Force a dry-run of the updater against live APIs (no changes applied)
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  "docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py --dry-run"

# Run the test suite locally
cd automation && python3 -m pytest -q
```

Secrets — the **Crafty JWT**, the **Dokploy API key**, and the playit **SECRET_KEY** — are never stored in this repo. The Crafty JWT lives in the server-side `config.json` (chmod 600); the Dokploy key and Crafty JWT are passed to `deploy.sh` as `$DOKPLOY_KEY` / `$CRAFTY_JWT`; redeploys use Dokploy deploy-webhook tokens, not the API key.

## green-axolotl pack (`green-axolotl/`)

- **`green-axolotl/green-axolotl-pack-br.mcpack`** — the **canonical Bedrock resource pack** (uuid `2d0e25e1-4630-4349-9923-e52792e38b6d`, v0.0.1). Re-textures the rare blue axolotl green and is served automatically to Bedrock clients by Geyser from `plugins/Geyser-Spigot/packs/`. See [docs/03-green-axolotl.md](docs/03-green-axolotl.md).
- **`green-axolotl/pack.zip`** — a **stale Java resource-pack experiment**, superseded by the Bedrock `.mcpack`. Kept for reference only; not deployed.

## Design & implementation

The authoritative design spec and the task-by-task implementation plan live under `docs/superpowers/`:

- [docs/superpowers/specs/2026-06-14-minecraft-update-automation-design.md](docs/superpowers/specs/2026-06-14-minecraft-update-automation-design.md) — design, current-state inventory, IDs, endpoints, risks.
- [docs/superpowers/plans/2026-06-14-minecraft-update-automation.md](docs/superpowers/plans/2026-06-14-minecraft-update-automation.md) — implementation plan.
