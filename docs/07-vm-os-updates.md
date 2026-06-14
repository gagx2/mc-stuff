# 07 — VM OS auto-updates & reboot resilience

The bottom layer: the **Ubuntu 24.04 VM** (on Proxmox) that runs Dokploy → Crafty →
Minecraft. Configured 2026-06-14. See also [05 — updates & automation](05-updates-automation.md)
for the app layer and [01 — architecture](01-architecture.md) for the stack.

## What's configured (in-guest, via `unattended-upgrades`)

Set up by [`infra/setup-vm-autoupdate.sh`](../infra/setup-vm-autoupdate.sh) (run once with `sudo`):

| Setting | Value |
|---|---|
| Update scope | **security + bug-fix (`-updates`)** — Ubuntu origins only |
| Daily run | **04:00 UTC** (`apt-daily-upgrade.timer`, pinned via override) |
| Auto-reboot | **yes, 04:30 UTC — only when `/var/run/reboot-required` exists** (kernel/libc bumps) |
| Cleanup | removes unused old kernels + deps |

Files: `/etc/apt/apt.conf.d/20auto-upgrades` (periodic schedule),
`/etc/apt/apt.conf.d/52unattended-upgrades-local` (origins + reboot),
`/etc/systemd/system/apt-daily-upgrade.timer.d/override.conf` (04:00 timing).
Timing is deliberately **after** the 03:30 MC maintenance and at a low-traffic hour.

## Docker is intentionally NOT auto-updated

`docker-ce` comes from Docker's own apt repo (origin `Docker`), which is **not** an allowed
Ubuntu origin — so unattended-upgrades leaves it alone. This is on purpose: a Docker daemon
upgrade restarts every container (a full-stack bounce). Update it deliberately, in a window:

```bash
ssh … 'sudo apt-get update && sudo apt-get install --only-upgrade docker-ce docker-ce-cli containerd.io'
```

## Reboot resilience — proven

A reboot bounces the whole stack; everything must come back on its own. **Verified by a
supervised test reboot on 2026-06-14: the full stack recovered in ~1 minute** — Docker +
all 7 Swarm services (`1/1`), Crafty, the MC server on 26.1.2, playit, and Geyser. Why it holds:

- Docker/containerd are **enabled on boot**; the Dokploy stack runs as **Swarm services** that
  Swarm reconciles automatically after boot (their `restart=no` is expected and fine).
- Plain-compose containers all have restart policies: crafty `always`, **playit `unless-stopped`**,
  traefik `always`. (playit's missing policy is what took it down on 2026-05-30 — now fixed.)
- `qemu-guest-agent` is active, so Proxmox does clean shutdowns.

## Proxmox-side (one-time, in the PVE UI — not automatable from the guest)

So the VM also recovers if the **Proxmox host** reboots:
1. VM → **Options → Start at boot = Yes** (`qm set <vmid> --onboot 1`).
2. VM → **Options → QEMU Guest Agent = Enabled** (the agent is already installed/active in the VM).

Proxmox has a REST API (`:8006`) + `qm`/`pvesh` and can schedule *backups*, but it has no
native guest-OS-update feature and no general task scheduler — guest updates correctly live
in-guest (above). Keeping the **Proxmox host** itself updated is a separate, deliberate task
(it's Debian; auto-reboot on the hypervisor is discouraged since it takes down all VMs).

## Other Dokploy projects on reboot

Verified 2026-06-14. The Dokploy stack is **Docker Swarm**; apps/databases are Swarm
services (auto-reconciled on boot), compose deploys rely on restart policies.

| Project | On reboot | Note |
|---|---|---|
| home-assistant | ✅ clean | compose, `restart=unless-stopped` |
| expense-tracker (backend + postgres) | ✅ recovers | Swarm; backend may crash-loop briefly waiting for its DB, then comes up |
| imggen (ui + mongo) | ⚠️ recovers, but loses its custom **Tailscale DNS** (`100.100.100.100`) on every (re)deploy → the per-minute **"Fix Tailscale DNS after deploy"** Dokploy schedule re-adds it (a `docker service update --dns-add`, which reschedules the task). Durable fix would be persistent DNS in the Dokploy app config. |
| crafty / Minecraft | ✅ clean | restart policies + jar perms fixed |

### Traefik heal-on-boot
`dokploy-traefik` (standalone, `restart=always`) **intermittently** fails on a cold reboot
with `attaching to network failed: context deadline exceeded` — a stale `dokploy-network`
overlay endpoint — and stays down, taking **all web UIs** with it (Minecraft is unaffected;
it bypasses traefik). Installed [`infra/setup-traefik-heal.sh`](../infra/setup-traefik-heal.sh)
(run once with sudo): a systemd oneshot (`dokploy-traefik-heal.service`) that runs ~45s after
Docker on every boot and, only if traefik is down, heals it
(`docker network disconnect -f dokploy-network dokploy-traefik` → `start` → reconnect).
Check after a boot: `journalctl -u dokploy-traefik-heal.service`.

> ⚠️ **Never** `docker network disconnect` the `lb-<network>` sandbox (shows as
> `dokploy-network-endpoint`) — it's the Swarm overlay VIP load-balancer; removing it breaks
> all service-to-service routing on the overlay and only `sudo systemctl restart docker` rebuilds it.

## Operating it

- **Logs:** `/var/log/unattended-upgrades/` and `journalctl -u apt-daily-upgrade.service`.
- **Is a reboot pending?** `[ -f /var/run/reboot-required ] && cat /var/run/reboot-required.pkgs`.
- **Apply pending now:** `sudo unattended-upgrade -v`.
- **Change scope to security-only:** delete the `-updates` line in
  `/etc/apt/apt.conf.d/52unattended-upgrades-local`.
- **Change/disable auto-reboot:** edit `Automatic-Reboot` / `Automatic-Reboot-Time` in the same
  file. Re-running `infra/setup-vm-autoupdate.sh` re-applies the managed defaults.
