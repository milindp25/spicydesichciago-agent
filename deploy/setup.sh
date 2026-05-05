#!/usr/bin/env bash
# Bootstrap script for a fresh Ubuntu 24.04 ARM (Oracle A1) VM.
#
# Idempotent — safe to re-run. Assumes you're logged in as `ubuntu`.
# Run with:
#   curl -sSL https://raw.githubusercontent.com/milindp25/spicydesichciago-agent/main/deploy/setup.sh | bash
#
# Or after cloning the repo:
#   bash deploy/setup.sh

set -euo pipefail

REPO_URL="https://github.com/milindp25/spicydesichciago-agent.git"
REPO_DIR="$HOME/spicydesichciago-agent"
DATA_DIR="/var/lib/spicy-desi/data"

echo "==> Updating apt"
sudo apt-get update -y
sudo apt-get upgrade -y

echo "==> Installing system packages"
sudo apt-get install -y \
	python3.12 \
	python3.12-venv \
	python3.12-dev \
	python3-pip \
	build-essential \
	pkg-config \
	libssl-dev \
	libffi-dev \
	git \
	curl \
	ca-certificates \
	debian-keyring \
	debian-archive-keyring \
	apt-transport-https \
	ufw

echo "==> Installing Caddy"
if ! command -v caddy >/dev/null 2>&1; then
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
		| sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
		| sudo tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
	sudo apt-get update -y
	sudo apt-get install -y caddy
fi

echo "==> Cloning repo"
if [ ! -d "$REPO_DIR" ]; then
	git clone "$REPO_URL" "$REPO_DIR"
else
	echo "    repo already exists at $REPO_DIR — pulling latest"
	git -C "$REPO_DIR" pull --ff-only
fi

echo "==> Creating persistent data dir at $DATA_DIR"
sudo mkdir -p "$DATA_DIR"
sudo chown -R ubuntu:ubuntu "$DATA_DIR"

echo "==> Setting up api/ venv"
cd "$REPO_DIR/api"
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -e .
mkdir -p data
# Symlink data dir to persistent volume
if [ ! -L data ] && [ ! "$(ls -A data 2>/dev/null)" ]; then
	rmdir data
	ln -s "$DATA_DIR" data
fi

echo "==> Setting up agent/ venv"
cd "$REPO_DIR/agent"
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -e .

echo "==> Creating .env files (templates) — EDIT THESE BEFORE STARTING SERVICES"
[ ! -f "$REPO_DIR/api/.env" ] && cp "$REPO_DIR/api/.env.example" "$REPO_DIR/api/.env"
[ ! -f "$REPO_DIR/agent/.env" ] && cp "$REPO_DIR/agent/.env.example" "$REPO_DIR/agent/.env"
chmod 600 "$REPO_DIR/api/.env" "$REPO_DIR/agent/.env"

echo "==> Installing systemd units"
sudo cp "$REPO_DIR/deploy/systemd/spicy-desi-api.service" /etc/systemd/system/
sudo cp "$REPO_DIR/deploy/systemd/spicy-desi-agent.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable spicy-desi-api spicy-desi-agent

echo "==> Installing Caddyfile"
sudo cp "$REPO_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
sudo systemctl enable caddy

echo "==> Configuring firewall (ufw)"
sudo ufw allow OpenSSH || true
sudo ufw allow 80/tcp || true
sudo ufw allow 443/tcp || true
# Oracle's iptables config sometimes blocks; flush conflicting rules.
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true
sudo ufw --force enable || true

echo ""
echo "============================================================"
echo "Setup complete. Next steps:"
echo ""
echo "1. Edit env files with real secrets:"
echo "     nano $REPO_DIR/api/.env"
echo "     nano $REPO_DIR/agent/.env"
echo ""
echo "2. Point DNS at this VM:"
echo "     api.spicydesichciago.com    -> $(curl -s ifconfig.me)"
echo "     agent.spicydesichciago.com  -> $(curl -s ifconfig.me)"
echo ""
echo "3. Start everything:"
echo "     sudo systemctl start spicy-desi-api spicy-desi-agent caddy"
echo ""
echo "4. Watch logs:"
echo "     sudo journalctl -u spicy-desi-api -u spicy-desi-agent -u caddy -f"
echo ""
echo "5. Update Twilio webhook to:"
echo "     https://agent.spicydesichciago.com/twilio/inbound"
echo "============================================================"
