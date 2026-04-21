#!/usr/bin/env bash
# scripts/deploy_server.sh — bootstrap the Trigonometry Sprint server on
# a fresh Ubuntu Lightsail instance.
#
# Usage (on the Lightsail instance as a regular user):
#   curl -sSL <raw-url-to-this-file> | bash
# or, after rsyncing this repo up:
#   bash scripts/deploy_server.sh
#
# What it does:
#   1. Installs Python 3, venv, build essentials.
#   2. Creates /opt/trigsprint and a Python venv there.
#   3. Installs server requirements.
#   4. Drops a systemd unit that runs uvicorn on :8000 and restarts on crash.
#   5. Opens the UFW firewall for port 8000 if UFW is active.
#
# Next steps after running:
#   * Add TLS: install caddy or nginx + certbot and proxy to 127.0.0.1:8000.
#   * Edit src/server_config.py in the CLIENT repo with this server's URL.
#   * Rebuild the client binaries and ship them.
set -euo pipefail

APP_DIR=/opt/trigsprint
SERVICE=/etc/systemd/system/trigsprint.service
PORT=8000

if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "[deploy] installing system packages..."
$SUDO apt-get update -y
$SUDO apt-get install -y python3 python3-venv python3-pip git build-essential

echo "[deploy] preparing $APP_DIR..."
$SUDO mkdir -p "$APP_DIR"
$SUDO chown -R "$USER:$USER" "$APP_DIR"

# If run in-tree (rsynced repo), copy the server bits up. If curl'd
# standalone, the operator needs to upload the `server/` dir themselves.
if [ -d "./server" ] && [ -f "./requirements-server.txt" ]; then
  echo "[deploy] copying server/ and requirements-server.txt..."
  cp -R server "$APP_DIR/"
  cp requirements-server.txt "$APP_DIR/"
fi

echo "[deploy] creating venv + installing deps..."
cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-server.txt
deactivate

echo "[deploy] writing systemd unit to $SERVICE..."
$SUDO tee "$SERVICE" >/dev/null <<UNIT
[Unit]
Description=Trigonometry Sprint API server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/uvicorn server.app:app --host 0.0.0.0 --port $PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

echo "[deploy] enabling service..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now trigsprint.service

if command -v ufw >/dev/null 2>&1 && $SUDO ufw status | grep -q "Status: active"; then
  echo "[deploy] allowing port $PORT through UFW..."
  $SUDO ufw allow $PORT/tcp
fi

echo "[deploy] done."
echo "  health check: curl http://localhost:$PORT/health"
echo "  service log : journalctl -u trigsprint -f"
