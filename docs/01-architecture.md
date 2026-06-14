# 01 — Architecture: the whole stack

How the green-axolotl Minecraft server is hosted, exposed, and administered — from the homelab VM up through Dokploy/Traefik, Crafty, and the playit.gg tunnel that carries Bedrock and Java players in.

Sibling docs: [Minecraft server](02-minecraft-server.md) · [Green Axolotl pack](03-green-axolotl.md) · [Bedrock connectivity](04-bedrock-connectivity.md) · [Updates & automation](05-updates-automation.md) · [Runbook](06-runbook.md)

---

## The host

A single homelab VM runs everything via Docker.

| Property | Value |
|---|---|
| Role | Dokploy host (Docker 29.5.2) |
| LAN address | `192.168.3.10` (behind home NAT) |
| Public egress IP | `217.146.109.73` (NAT'd; **no inbound port-forwarding** — the public tunnel is playit.gg, not this IP) |
| Tailscale address | `100.65.140.26` |
| Tailscale admin domains | `crafty.tail.keeso.com`, `dokploy.tail.keeso.com` |
| Last boot | 2026-05-30 15:54 |

The box sits behind home NAT with no inbound forwarding, so the public IP (`217.146.109.73`) is egress only. Inbound player traffic arrives through the **playit.gg** tunnel (see the connection path below). Admin access is over **Tailscale** (the `*.tail.keeso.com` names) or **SSH**.

### SSH

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210
```

The `alex` user is in the `docker` group (so `docker ...` works directly) but has **no passwordless sudo**.

---

## Dokploy (the deployment platform)

[Dokploy](https://dokploy.com) **v0.29.8** is the PaaS layer that manages the Docker Compose stacks. It ships a built-in **Traefik** reverse proxy with **Let's Encrypt** for automatic TLS on any HTTP services it exposes.

- API base: `http://localhost:3000/api` (reachable on the host, e.g. via SSH).
- Auth header: `x-api-key`. REST GETs use plain query params; POST mutations use a JSON body.
- Organization ID: `eFbswAqh7vlP_F7SfdS8D`.
- All services run on the **local** server (`serverId: null`).
- Redeploys are triggered per-compose via **deploy webhooks** (`POST /api/deploy/compose/<webhookToken>`), which need no API key.

### Project & compose IDs

Everything for this server lives in one Dokploy project, **`crafty`**, holding two `raw` composes:

| Thing | ID |
|---|---|
| Project `crafty` | `Di61CG06nx38RaT287xRV` (env `8med8lHP8WC2M-OdQhlXW`) |
| Compose **ui** (Crafty) | `p0FzCTSvUDQkF35o0fd8i` (webhook token `P4G6U5tnpT1UbETaPDfcx`) |
| Compose **playit-agent** | `Up4B06-EaIzJuYH3mxgTj` (webhook token `FohNmoNN_pzIgkfljoAJo`) |

> A separate `dokploy-server` schedule, **"Daily Docker Cleanup at 3am"** (`0 3 * * *`, `docker system prune --force`), runs nightly. The maintenance automation runs at **3:30** to stay clear of it — see [Updates & automation](05-updates-automation.md).

---

## Crafty Controller (the Minecraft control panel)

[Crafty Controller](https://craftycontrol.com) runs inside the **ui** compose as `crafty_container` (image `registry.gitlab.com/crafty-controller/crafty-4:latest`). It is the web UI / API used to start, stop, back up, and edit the Minecraft server.

**Key fact:** Crafty runs the Minecraft server as a **child Java process *inside* `crafty_container`** — there is **no separate Minecraft container**. The Paper JVM, all plugins, and the world files all live in Crafty's volumes and run in Crafty's process tree.

- API base: `https://localhost:8443/api/v2` (self-signed TLS).
- Auth: `Authorization: Bearer <Crafty JWT>` (referred to by name only; see the runbook for rotation).
- Admin UI: `https://crafty.tail.keeso.com` over Tailscale.
- Persistent host volumes (survive container recreation): `/var/lib/docker/volumes/crafty/{config,backups,import,logs,servers}`.

Details of the Paper server, plugins, and ports are in [Minecraft server](02-minecraft-server.md).

---

## Container inventory

The Dokploy host is shared with several **unrelated co-tenant** apps. Only `crafty_container` and the playit-agent belong to this Minecraft stack; the rest are listed so you don't mistake them for part of it.

| Container | Image | Compose / project | Role |
|---|---|---|---|
| `crafty_container` | `registry.gitlab.com/crafty-controller/crafty-4:latest` | ui (`p0FzCTSvUDQkF35o0fd8i`), project `crafty` | Crafty Controller + the Minecraft (Paper) server as an in-container child process. `restart: always`. Publishes `8123`, `19132/udp`, `25500-25600`. |
| playit-agent | `ghcr.io/playit-cloud/playit-agent:0.17` → migrating to `:1.0` | playit (`Up4B06-EaIzJuYH3mxgTj`), project `crafty` | Public tunnel to playit.gg. `network_mode: host`, `SECRET_KEY` set. Originally **no restart policy** (the cause of the outage) — fixed to `restart: unless-stopped`. See [Bedrock connectivity](04-bedrock-connectivity.md). |
| traefik | (Dokploy-managed) | Dokploy core | Reverse proxy + Let's Encrypt TLS for HTTP services. **Unrelated to this stack's gameplay traffic.** |
| imggen | — | unrelated co-tenant | Separate app on the same host. Not part of the MC stack. |
| home-assistant | — | unrelated co-tenant | Home automation. Not part of the MC stack. |
| postgres | — | unrelated co-tenant | Database for other apps. |
| mongo | — | unrelated co-tenant | Database for other apps. |
| redis | — | unrelated co-tenant | Cache for other apps. |

> The nightly `docker system prune --force` deleted the **stopped** playit container after the 2026-05-30 reboot (it had no restart policy and never came back up). Adding `restart: unless-stopped` and moving to the rolling `:1.0` tag is the durable fix; the maintenance script also re-checks playit liveness each night.

---

## Connection path (how players reach the server)

There is no inbound port-forward on the home NAT. All player traffic enters through the **playit.gg** tunnel, which terminates on the host and hands off to the published container ports. Bedrock (Android/console) players are bridged into the Java server by **Geyser**.

```
Bedrock phone ──▶ playit.gg tunnel ──▶ host UDP 19132 ──▶ Geyser ──▶ Paper (Java)
   (Android/console)                    (Geyser listener)   (bridge)   (mc-paper-1)

Java client   ──▶ playit.gg tunnel ──▶ host 25565 ──▶ Paper (Java)
   (PC)                                  (server-port)
```

- **Bedrock** clients hit the Geyser UDP listener on **`19132/udp`**; Geyser translates the Bedrock protocol to Java and connects to Paper. Floodgate lets them in without a Java/Microsoft account (`online-mode=true` is bypassed for Bedrock).
- **Java** clients reach Paper's `server-port` (`25565`, inside the `25500-25600` published range) straight through the tunnel.
- The playit-agent runs `network_mode: host`, so the tunnel reaches the published host ports directly.

See [Bedrock connectivity](04-bedrock-connectivity.md) for the Geyser/Floodgate/Via stack and the protocol-lag problem.

### Published ports

| Port | Proto | Purpose |
|---|---|---|
| `19132` | UDP | Geyser — Bedrock entry point |
| `25500-25600` | TCP | Java server range (Paper's `server-port` = `25565` lives here) |
| `8123` | TCP | Crafty / map service port |

---

## How to reach things

| Target | How |
|---|---|
| Crafty admin UI | `https://crafty.tail.keeso.com` (over Tailscale; self-signed/Let's Encrypt) |
| Dokploy admin UI | `https://dokploy.tail.keeso.com` (over Tailscale) |
| Dokploy API | `http://localhost:3000/api` on the host (header `x-api-key: $DOKPLOY_KEY`) |
| Crafty API | `https://localhost:8443/api/v2` on the host (header `Authorization: Bearer $CRAFTY_JWT`, self-signed TLS) |
| Shell / Docker | `ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210` |
| Tailscale (raw) | host `100.65.140.26`; LAN `192.168.3.10` |
| Game (Bedrock/Java) | via the playit.gg tunnel — see [Bedrock connectivity](04-bedrock-connectivity.md) for the current address |

> Secrets (the Crafty JWT, Dokploy API key, and playit `SECRET_KEY`) are referenced by name only. Use `$CRAFTY_JWT` / `$DOKPLOY_KEY` placeholders in commands; see [Runbook](06-runbook.md) for where they live and how to rotate them.
