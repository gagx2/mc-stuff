# Bedrock Connectivity

How Android/console (Bedrock) players reach the Java server — and the recurring "can't connect after a Minecraft update" problem, why it happens, and why the fix is to update **Geyser**, not Paper.

## The connection chain

A Bedrock client speaks a completely different network protocol than a Java server. Four plugins bridge that gap on the server side:

```
Bedrock phone/console
        │  (Bedrock protocol, UDP :19132)
        ▼
   Geyser ──────── translates Bedrock ⇄ Java protocol
        │
   Floodgate ───── lets Bedrock players join without a Java/Microsoft account
        │
   ViaVersion / ViaBackwards ── bridge Java-protocol version gaps
        │
        ▼
   Paper 1.21.8 (Java server, :25565)
```

| Component | Role | Tracks |
|-----------|------|--------|
| **Geyser** | Bedrock ⇄ Java protocol translation. The entry point for every Bedrock client. | the **Bedrock** protocol version |
| **Floodgate** | Authenticates Bedrock players without a Java/Microsoft account, so `online-mode=true` can stay on for Java players. | Bedrock auth / Geyser companion |
| **ViaVersion** | Lets newer Java clients connect to an older Java server. | newer Java protocol versions |
| **ViaBackwards** | Lets older Java clients connect to a newer Java server. | older Java protocol versions |

All four run as plugins inside the same Paper server. Bedrock traffic arrives on UDP **19132** (published by the Crafty compose); Java traffic uses **25565**. See [architecture](01-architecture.md) for the full network path (Bedrock phone → playit tunnel → host:19132 → Geyser → Paper).

## Why "can't connect after a Minecraft update" happens

> **Key fact: GEYSER is the component that tracks the Bedrock protocol.**

Minecraft Bedrock auto-updates silently on phones and consoles. When Mojang ships a new Bedrock release, it bumps the Bedrock **protocol version**. A Geyser build only knows the protocol versions that existed when it was built.

So when a phone auto-updates ahead of the server's Geyser:

- The new client connects to Geyser speaking a protocol the stale Geyser build doesn't recognize.
- Geyser rejects it with **"Outdated client"** (or, depending on direction, **"Outdated server"**).
- Java players are completely unaffected — they don't go through Geyser at all.

**The fix is to update Geyser** (and usually Floodgate alongside it). It is **NOT** a Paper problem and updating Paper does nothing for this. The plugin stack on this server had been frozen since 2026-02-20, which is exactly why Bedrock players kept getting locked out after their phones updated.

### Why the Java/Paper version can lag

The Java server does **not** have to chase the latest Minecraft version to keep Bedrock players online. Geyser plus ViaVersion/ViaBackwards bridge the protocol gap:

- **Geyser** maps whatever the current Bedrock client speaks onto the Java protocol the server runs.
- **ViaVersion/ViaBackwards** absorb the gap between the Java client protocol Geyser targets and the actual Java server protocol.

That layering means Paper can sit a version or two behind and Bedrock connectivity still works — as long as **Geyser is current for the live Bedrock protocol**. Geyser currency is the thing that matters for this failure mode.

## Current upstream versions (as of 2026-06-14)

| Plugin | Latest |
|--------|--------|
| Geyser | **2.10.1 build 1165** |
| Floodgate | **2.2.5 build 132** |
| ViaVersion | **5.9.1** |
| ViaBackwards | **5.9.1** |

### Always-latest download URLs

Geyser and Floodgate publish an "always latest build" endpoint, so these URLs never need editing:

```
# Geyser (Spigot/Paper jar)
https://download.geysermc.org/v2/projects/geyser/versions/latest/builds/latest/downloads/spigot

# Floodgate (Spigot/Paper jar)
https://download.geysermc.org/v2/projects/floodgate/versions/latest/builds/latest/downloads/spigot
```

To grab the current Geyser jar by hand from the host:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210
docker exec crafty_container python3 - <<'PY'
import urllib.request
url="https://download.geysermc.org/v2/projects/geyser/versions/latest/builds/latest/downloads/spigot"
urllib.request.urlretrieve(url, "/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/plugins/Geyser-Spigot.jar")
print("downloaded")
PY
```

ViaVersion/ViaBackwards come from GitHub releases (`https://api.github.com/repos/ViaVersion/ViaVersion/releases/latest` and `.../ViaBackwards/releases/latest`), versioned by semver tag rather than a build number.

## The inherent lag — and why it self-heals

There is an **unavoidable hours-to-days gap** between a new Bedrock release going live on phones and a Geyser build existing that supports it. GeyserMC has to add the new protocol mappings and cut a build first. During that window, freshly-updated Bedrock clients simply cannot connect, no matter what you do on the server — there is nothing to update **to** yet. This lag cannot be fully eliminated.

What *can* be eliminated is the much larger lag from a stale, frozen plugin stack. The nightly automation pulls the latest Geyser/Floodgate/ViaVersion/ViaBackwards every night, so once GeyserMC ships a supporting build, the server picks it up within ~24 hours automatically. In practice this makes the "can't connect after a Minecraft update" problem **mostly self-healing**: it resolves on its own a day or so after the Bedrock release, with no manual intervention.

If you can't wait for the nightly run, force an immediate update:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210
docker exec crafty_container python3 /crafty/import/autoupdate/mc-autoupdate.py
```

This downloads any newer Geyser/Floodgate/Via, then restarts the server.

See [updates automation](05-updates-automation.md) for the full nightly process, the in-Crafty updater logic, manual procedures, and rollback.
