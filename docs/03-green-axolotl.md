# Green Axolotl Customization

The server's signature feature: a `/greenaxolotl` command that hands out a rare green axolotl spawn egg, paired with a Bedrock resource pack that re-textures the rare blue axolotl green so it actually *looks* green on phones. This page documents the command, the pack, and exactly how to update the pack.

---

## The `/greenaxolotl` command (MyCommand)

Custom commands are defined by the **MyCommand** plugin (`MyCommand.jar`) in its `commands.yml`:

```
plugins/MyCommand/commands.yml
```

The command definition:

```yaml
greenaxolotl:
  command: '/greenaxolotl'
  type: RUN_CONSOLE
  permission-required: false
  cooldown: 300
  runcmd:
  - 'give $player minecraft:axolotl_spawn_egg[minecraft:entity_data={id:"minecraft:axolotl",Variant:4}] 1'
  - 'tell $player &2You received a Green Axolotl spawn egg!'
```

What each piece does:

| Field | Value | Meaning |
|-------|-------|---------|
| `type` | `RUN_CONSOLE` | Runs the `runcmd` lines as **console** (so no player op/permission is needed to `give`). |
| `permission-required` | `false` | Anyone can run `/greenaxolotl`. |
| `cooldown` | `300` | 300 seconds (5 min) per player between uses, to stop spam. |
| `runcmd[0]` | `give … axolotl_spawn_egg[…Variant:4] 1` | Gives one axolotl spawn egg pre-set to **Variant 4**. |
| `runcmd[1]` | `tell $player &2…` | Sends a dark-green (`&2`) confirmation message. |

`$player` is MyCommand's placeholder for whoever ran the command.

### Why `Variant:4`?

Minecraft axolotls have five variants. The `minecraft:entity_data={id:"minecraft:axolotl",Variant:4}` component on the spawn egg pre-bakes the variant into the egg's NBT, so the axolotl spawns as that variant directly:

| Variant | Color | Rarity |
|---------|-------|--------|
| 0 | Lucy (pink) | common |
| 1 | Wild (brown) | common |
| 2 | Gold | common |
| 3 | Cyan | common |
| **4** | **Blue** | **rare (~1 in 1200 naturally)** |

**Variant 4 is the rare blue axolotl** — the one that normally takes thousands of breeds to get. The resource pack below re-skins that blue variant to **green/lime**, so the egg from `/greenaxolotl` produces what players see as a rare *green* axolotl. The mechanics stay vanilla "blue"; only the texture is swapped.

---

## The Bedrock resource pack

```
green-axolotl/green-axolotl-pack-br.mcpack   <- canonical copy in this repo
```

This is a **Bedrock-edition** pack (`.mcpack`). Its `manifest.json`:

| Field | Value |
|-------|-------|
| `name` | `Green Axolotl Pack` |
| `description` | `Changes the rare blue axolotl texture into a rare green!` |
| `uuid` (header) | `2d0e25e1-4630-4349-9923-e52792e38b6d` |
| `version` | `0.0.1` (`[0, 0, 1]`) |
| module type | `resources` |

It works by overriding `textures/entity/axolotl/axolotl_blue.png` (the rare blue variant) with a green texture, so Variant 4 renders green on Bedrock clients.

### How clients receive it — Geyser auto-serves it

Bedrock players never install this manually. **Geyser** ships every pack it finds in its packs folder to connecting Bedrock clients automatically:

```
plugins/Geyser-Spigot/packs/green-axolotl-pack-br.mcpack
```

On connect, Geyser offers the pack to the Bedrock client, which downloads and applies it for that session. No client-side action, no marketplace, nothing to enable. (Java clients are unaffected — Java packs work differently; see below.)

> See [Bedrock connectivity](04-bedrock-connectivity.md) for how Geyser bridges Bedrock clients to the Paper server in the first place.

### `pack.zip` is a stale Java experiment — ignore it

The repo also contains:

```
green-axolotl/pack.zip
```

This is **not** the pack in use. It is an earlier **Java-edition** resource pack experiment: it has a `pack.mcmeta` and `assets/minecraft/...` layout (Java format), *not* the Bedrock `manifest.json` + top-level `textures/` layout. It targets a different edition and has been **superseded** by `green-axolotl-pack-br.mcpack`. Treat `pack.zip` as a leftover artifact — the canonical, live pack is the `.mcpack`.

---

## How to update the pack

The flow is: edit textures locally, bump the manifest version, repackage as a `.mcpack`, push it into Geyser's packs folder, and restart the server so Geyser re-reads the folder.

### 1. Edit and bump the version

A `.mcpack` is just a ZIP. Unzip it, edit the textures (e.g. `textures/entity/axolotl/axolotl_blue.png`), then **bump the `version` array** in `manifest.json` so clients re-download instead of using a cached copy:

```jsonc
"version": [ 0, 0, 2 ]   // was [0, 0, 1] — increment on every change
```

Bump **both** the header `version` and the module `version` so they stay in sync. Keep the `uuid`s the same (a new UUID would register as a different pack).

### 2. Repackage as `.mcpack`

Zip the contents (the `manifest.json` must be at the **root** of the archive, not inside a subfolder) and name it `.mcpack`:

```bash
cd green-axolotl/pack-src        # the unpacked folder
zip -r ../green-axolotl-pack-br.mcpack . -x '.*'
```

Commit the updated `.mcpack` so the repo copy stays canonical.

### 3. Copy it into Geyser's packs folder on the server

The packs live inside `crafty_container` at
`/crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/plugins/Geyser-Spigot/packs/`.

**Option A — stream it in over SSH + `docker exec`** (no scp needed; pipes the local file straight into the container):

```bash
cat green-axolotl/green-axolotl-pack-br.mcpack | \
  ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  "docker exec -i crafty_container sh -c 'cat > /crafty/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/plugins/Geyser-Spigot/packs/green-axolotl-pack-br.mcpack'"
```

**Option B — Crafty file manager:** open the server in the Crafty UI (`crafty.tail.keeso.com`), browse to `plugins/Geyser-Spigot/packs/`, and upload the new `.mcpack` (overwriting the old one).

> Replacing the same filename is fine — Geyser keys packs by their manifest `uuid` + `version`, which is exactly why step 1's version bump matters: it forces clients to fetch the new copy.

### 4. Restart the server

Geyser only re-scans `packs/` on startup, so restart so it picks up the changed pack:

```bash
ssh -i /home/alex/ssh-keys/dokploy/dokploy-key-v2 alex@172.16.103.251 -p 6210 -- \
  "docker exec crafty_container python3 -c \"import urllib.request,ssl,json; ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE; req=urllib.request.Request('https://localhost:8443/api/v2/servers/394a3479-b8e9-4f4f-aa36-49c87eafe548/action/restart_server', method='POST', headers={'Authorization':'Bearer '+'\$CRAFTY_JWT'}); print(urllib.request.urlopen(req, context=ctx).read())\""
```

Or simply hit **Restart** in the Crafty UI. (`$CRAFTY_JWT` is the Crafty API token — pass it by reference, never paste the literal token.)

Reconnect on a Bedrock client and the new texture should download on join. If a phone still shows the old skin, fully quit and rejoin — the version bump invalidates the cached pack.

---

## Quick reference

| Thing | Value |
|-------|-------|
| Command | `/greenaxolotl` (300s cooldown, no permission) |
| Command def file | `plugins/MyCommand/commands.yml` |
| Egg variant | `Variant:4` = rare blue axolotl, re-skinned green by the pack |
| Live Bedrock pack | `plugins/Geyser-Spigot/packs/green-axolotl-pack-br.mcpack` |
| Pack UUID / version | `2d0e25e1-4630-4349-9923-e52792e38b6d` / `0.0.1` |
| Canonical repo copy | `green-axolotl/green-axolotl-pack-br.mcpack` |
| Stale Java experiment | `green-axolotl/pack.zip` (superseded — ignore) |
| Served by | Geyser, automatically, to all Bedrock clients on join |

See also: [Bedrock connectivity](04-bedrock-connectivity.md).
