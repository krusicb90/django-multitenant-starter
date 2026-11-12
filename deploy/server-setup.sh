#!/usr/bin/env bash
# One-time bootstrap of a fresh Ubuntu 24.04 host. Run as root: bash server-setup.sh
# Idempotent: safe to run again.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/app}"
SWAP_SIZE="${SWAP_SIZE:-2G}"

echo "==> [1/8] System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q ca-certificates curl gnupg ufw fail2ban unattended-upgrades jq rclone

echo "==> [2/8] Docker Engine and the Compose plugin"
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    # shellcheck disable=SC1091
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

# Log rotation for every container that does not set its own.
cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true
}
JSON
systemctl restart docker

echo "==> [3/8] Swap (${SWAP_SIZE})"
if ! swapon --show | grep -q '/swapfile'; then
    fallocate -l "$SWAP_SIZE" /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
cat > /etc/sysctl.d/90-app.conf <<'SYSCTL'
vm.swappiness=10
net.core.somaxconn=1024
SYSCTL
sysctl --system >/dev/null

echo "==> [4/8] Firewall"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> [5/8] SSH: key authentication only"
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/90-hardening.conf <<'SSHD'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 4
SSHD
systemctl reload ssh || systemctl reload sshd

echo "==> [6/8] fail2ban and unattended upgrades"
cat > /etc/fail2ban/jail.d/sshd.local <<'F2B'
[sshd]
enabled = true
maxretry = 5
bantime = 1h
F2B
systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> [7/8] Application directories"
mkdir -p "$APP_DIR"/{backups/daily,backups/weekly,backups/predeploy,ssl}
chmod 700 "$APP_DIR/ssl" "$APP_DIR/backups"
touch "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"

echo "==> [8/8] Cron: nightly backup and image cleanup"
cat > /etc/cron.d/app <<CRON
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
APP_DIR=$APP_DIR
# Nightly backup of every database
30 2 * * * root $APP_DIR/backup.sh >> /var/log/app-backup.log 2>&1
# Weekly cleanup of unused images and build cache
0 4 * * 0 root docker system prune -af --filter "until=168h" >> /var/log/app-prune.log 2>&1
CRON
chmod 644 /etc/cron.d/app
cat > /etc/logrotate.d/app <<'LR'
/var/log/app-*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
}
LR

cat <<DONE

Server bootstrap complete. Next steps:
  1. Put the TLS certificate in $APP_DIR/ssl/cert.pem and key.pem (chmod 600).
  2. Copy deploy/docker-compose.prod.yml -> $APP_DIR/docker-compose.yml
          deploy/nginx.conf.template  -> $APP_DIR/nginx.conf.template
          deploy/deploy.sh, backup.sh, restore.sh -> $APP_DIR/ (chmod +x)
  3. Fill $APP_DIR/.env (see deploy/.env.production.example).
  4. $APP_DIR/deploy.sh <image-tag>
DONE
