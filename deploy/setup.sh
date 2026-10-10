#!/usr/bin/env bash
# Run on the Oracle Ubuntu VM, from the cloned repo:  bash deploy/setup.sh
set -euo pipefail
cd "$(dirname "$0")"

# 1. Docker
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

# 2. Open ports 80/443 in the VM firewall (Oracle Ubuntu images block them by default)
sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
sudo apt-get install -y iptables-persistent >/dev/null 2>&1 || true
sudo netfilter-persistent save 2>/dev/null || true

# 3. Secrets file (stays on this server only)
if [ ! -f .env ]; then
  read -rp "Admin phone number: " ADMIN_PHONE
  read -rsp "Admin password (8+ chars): " ADMIN_PW; echo
  umask 077
  cat > .env <<EOF
BAGKEEPER_SECRET=$(openssl rand -hex 32)
BAGKEEPER_ADMIN_NAME=Owner
BAGKEEPER_ADMIN_PHONE=$ADMIN_PHONE
BAGKEEPER_ADMIN_PASSWORD=$ADMIN_PW
EOF
fi

# 4. Start
mkdir -p data
sudo docker compose up -d --build

# 5. Nightly backup at 03:00
chmod +x backup.sh
( crontab -l 2>/dev/null | grep -v backup.sh ; echo "0 3 * * * $(pwd)/backup.sh" ) | crontab -

echo "Up. Point DNS bagkeeper.hafizassist.com -> this VM's public IP (DNS only), then open https://bagkeeper.hafizassist.com"
