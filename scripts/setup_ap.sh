#!/bin/bash
# setup_ap.sh — Поднять WiFi точку доступа VoiceTerm с captive portal

set -e

IFACE="wlan0"
AP_IP="192.168.4.1"
SUBNET="192.168.4.0/24"
SSID="VoiceTerm"
PORTAL_PORT="8080"

echo "[AP] Установка hostapd и dnsmasq..."
apt-get install -y hostapd dnsmasq iptables

echo "[AP] Настройка hostapd..."
cat > /etc/hostapd/hostapd.conf << EOF
interface=${IFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
EOF

sed -i 's|#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

echo "[AP] Настройка dnsmasq..."
cat > /etc/dnsmasq.conf << EOF
interface=${IFACE}
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
address=/#/${AP_IP}
EOF

echo "[AP] Назначение IP на ${IFACE}..."
ip addr add ${AP_IP}/24 dev ${IFACE} 2>/dev/null || true

echo "[AP] Запуск сервисов..."
systemctl unmask hostapd
systemctl enable hostapd
systemctl restart hostapd
systemctl restart dnsmasq

echo "[AP] Настройка iptables для captive portal..."
iptables -t nat -F
iptables -t nat -A PREROUTING -i ${IFACE} -p tcp --dport 80 -j REDIRECT --to-port ${PORTAL_PORT}
iptables -t nat -A PREROUTING -i ${IFACE} -p tcp --dport 443 -j REDIRECT --to-port ${PORTAL_PORT}

echo "[AP] Точка доступа '${SSID}' запущена на ${AP_IP}:${PORTAL_PORT}"
