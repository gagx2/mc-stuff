#!/usr/bin/env bash
# Configure automatic OS updates + auto-reboot for the Dokploy Ubuntu VM
# (the host that runs Crafty/Minecraft/playit). Run AS ROOT:
#
#     sudo bash setup-vm-autoupdate.sh
#
# Scope:        security + bug-fix (-updates)   (remove the -updates line below for security-only)
# Auto-reboot:  yes, at 04:30 UTC, ONLY when /var/run/reboot-required exists (kernel/libc bumps)
# Timing:       daily upgrade run pinned to 04:00 UTC (after the 03:30 MC job), so a needed
#               reboot at 04:30 is same-day and off players' prime time.
# Idempotent:   safe to re-run.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "ERROR: run with sudo (needs root to edit /etc/apt)"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "==> 1/5 ensure tooling installed"
apt-get update -qq
apt-get install -y -qq unattended-upgrades apt-listchanges update-notifier-common >/dev/null

echo "==> 2/5 periodic apt schedule -> /etc/apt/apt.conf.d/20auto-upgrades"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

echo "==> 3/5 unattended-upgrades policy -> /etc/apt/apt.conf.d/52unattended-upgrades-local"
cat > /etc/apt/apt.conf.d/52unattended-upgrades-local <<'EOF'
// Managed by mc-stuff/infra/setup-vm-autoupdate.sh (green-axolotl VM).
// Scope = security + bug-fix (-updates). For security-only, delete the -updates line.
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}";
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
    "${distro_id}:${distro_codename}-updates";
};
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-WithUsers "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF

echo "==> 4/5 pin the daily upgrade run to 04:00 UTC"
mkdir -p /etc/systemd/system/apt-daily-upgrade.timer.d
cat > /etc/systemd/system/apt-daily-upgrade.timer.d/override.conf <<'EOF'
[Timer]
OnCalendar=
OnCalendar=*-*-* 04:00
RandomizedDelaySec=5m
Persistent=true
EOF
systemctl daemon-reload
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
systemctl restart apt-daily-upgrade.timer

echo "==> 5/5 validate (dry-run; shows what WOULD upgrade under the new scope)"
unattended-upgrade --dry-run -v 2>&1 | tail -n 20 || true

echo
echo "============================================================"
echo " effective settings"
echo "   scope        : security + -updates"
echo "   auto-reboot  : yes @ 04:30 UTC, only when a reboot is required"
echo "   daily run    : 04:00 UTC"
systemctl list-timers apt-daily-upgrade.timer --no-pager 2>/dev/null | sed -n '2p'
echo "   reboot pending now? : $([ -f /var/run/reboot-required ] && echo YES || echo no)"
echo "============================================================"
echo
echo "To apply any pending updates immediately:   sudo unattended-upgrade -v"
echo "To test recovery now (supervised reboot):   sudo reboot"
echo "Logs:  /var/log/unattended-upgrades/   |   journalctl -u apt-daily-upgrade.service"
