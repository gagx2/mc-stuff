# The Minecraft Server (`mc-paper-1`)

The actual game server: a PaperMC instance running as a Java child process inside the Crafty Controller container. This doc covers what it is, how it's configured, which plugins are live, what's dead weight, and how to reach the files. For the network path that gets Bedrock phones to it see [Bedrock connectivity](04-bedrock-connectivity.md); for the green axolotl customization see [green-axolotl](03-green-axolotl.md).

## At a glance

| Property | Value |
| --- | --- |
| Server name | `mc-paper-1` |
| Crafty server id | `394a3479-b8e9-4f4f-aa36-49c87eafe548` |
| Software | PaperMC **1.21.8** (`paper-1.21.8.jar`) |
| Launch command | `java -Xms1000M -Xmx2000M -jar paper.jar nogui` |
| Heap | min 1000 MB / max 2000 MB |
| Java | **25**, in-container (provided by the Crafty image) |
| Managed by | Crafty Controller 4.x (runs the Java process, exposes the API) |
| Paper update URL | `https://jars.arcadiatech.org/paper/1.21.8/paper.jar` (Crafty mirror) |

Crafty runs `mc-paper-1` as a managed Java subprocess inside `crafty_container`. There is no separate Minecraft container; the JVM lives inside Crafty and its files sit on a host-bound volume (see [Files & volumes](#files--volumes)).

> **The container has `python3` only — no `curl`, `wget`, or `unzip`.** It does have outbound internet. This is why the in-container updater ([05-updates-automation.md](05-updates-automation.md)) is pure-Python stdlib.

## Ports

| Port | Scope | Purpose |
| --- | --- | --- |
| `25565` | internal | `server-port` — the Java edition listener inside the container |
| `25500-25600` | published (host) | Java-edition port range exposed by the Crafty compose |
| `19132/udp` | published (host) | Bedrock listener, served by Geyser (Bedrock clients connect here) |

The `25500-25600` range and `19132/udp` are published on the host by the Crafty compose (`crafty_container`). Bedrock traffic does not touch `25565`; it lands on `19132/udp` and Geyser translates it into the Java server. See [Bedrock connectivity](04-bedrock-connectivity.md) for the full phone-to-Paper path.

## Active plugins

Five plugins are live in `plugins/`. They were last hand-updated **2026-02-20**; the automation now keeps Geyser/Floodgate/Via current ([05-updates-automation.md](05-updates-automation.md)).

| Plugin (jar) | Role |
| --- | --- |
| `Geyser-Spigot.jar` | Bedrock-to-Java protocol bridge — lets Bedrock (Android/console) clients join on `19132/udp` |
| `floodgate-spigot.jar` | Lets Bedrock players join **without a Java/Microsoft account** (this is why `online-mode=true` is safe — see below) |
| `ViaVersion-5.7.1.jar` | Lets **newer** clients connect to this server version |
| `ViaBackwards-5.7.1.jar` | Lets **older** clients connect to this server version |
| `MyCommand.jar` | Custom command engine — defines `/greenaxolotl` (see [green-axolotl](03-green-axolotl.md)) |

## Dead weight (cleanup candidates)

These directories live under `plugins/` but have **no matching jar** — they are orphaned data or backups, not active plugins. They are safe to remove (back up first if unsure).

| Path | What it is | Why it's safe to drop |
| --- | --- | --- |
| `plugins/Essentials/` | Leftover Essentials data dir | No EssentialsX jar is installed — dormant data only |
| `plugins/Updater/` | Bukkit updater-lib config | Dormant config for an updater library that isn't active |
| `plugins/old_plugins_backup/` | Feb-20 backup snapshot | Old jars (Via 5.5.0, old Geyser/Floodgate) kept as a manual rollback stash |
| `plugins/spark/` | Profiler data | **`spark` is Paper-bundled** — Paper ships and manages it; this is its data dir, not a plugin you installed |
| `.paper-remapped/` | Paper's remap cache | Paper-generated cache, regenerated as needed |

`old_plugins_backup/` doubles as a rollback source: if a Via/Geyser/Floodgate update breaks something, the prior jars are here. Otherwise these are clutter.

## Key `server.properties` values

| Key | Value | Note |
| --- | --- | --- |
| `gamemode` | `creative` | |
| `difficulty` | `easy` | |
| `max-players` | `20` | |
| `server-port` | `25565` | internal listener |
| `online-mode` | `true` | Bedrock players bypass this via **Floodgate**, so genuine Java accounts are still verified while Bedrock players join account-free |

## Files & volumes

Crafty's data lives on host bind-mount volumes that **persist across container recreation** (so redeploys/image pulls don't lose the world):

```
/var/lib/docker/volumes/crafty/
├── config     Crafty's own config + DB
├── backups    Crafty-managed server backups
├── import     import staging (also where the autoupdate scripts live)
├── logs       Crafty logs
└── servers    each managed server, by id
```

Inside the container the same data is at `/crafty/...`. The server's own directory:

```
/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/
```

## Reaching the server files

SSH to the host, then `docker exec` into the Crafty container:

```bash
# 1. SSH to the Dokploy host
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210

# 2. Open a shell inside the Crafty container
docker exec -it crafty_container sh

# 3. The server lives here
cd /crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/
ls plugins/
```

One-liner to peek at the active plugin jars from your workstation:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 \
  'docker exec crafty_container ls /crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/plugins'
```

Remember: the container has `python3` but **no** `curl`/`wget`/`unzip`, so use `python3` for any download/zip inspection inside it (this is exactly what `mc-autoupdate.py` does — see [05-updates-automation.md](05-updates-automation.md)).

## See also

- [03-green-axolotl.md](03-green-axolotl.md) — the `/greenaxolotl` command and the Bedrock resource pack served by Geyser.
- [04-bedrock-connectivity.md](04-bedrock-connectivity.md) — how Android/Bedrock clients reach this server through Geyser/Floodgate/Via.
