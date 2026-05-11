#!/bin/bash
# docker/entrypoint.sh — Подготовка окружения и запуск VoiceTerm

set -e

echo "========================================"
echo "  VoiceTerm starting..."
echo "========================================"

if [ ! -S /var/run/dbus/system_bus_socket ]; then
    echo "[entrypoint] Запуск dbus-daemon..."
    mkdir -p /var/run/dbus
    dbus-daemon --system --fork
    sleep 1
fi

if ! pgrep -x bluetoothd > /dev/null 2>&1; then
    echo "[entrypoint] Запуск bluetoothd..."
    bluetoothd --nodetach &
    sleep 2
fi

if [ -z "$PULSE_SERVER" ] || [ ! -S "/run/user/1000/pulse/native" ]; then
    echo "[entrypoint] Запуск PulseAudio..."
    pulseaudio --start --exit-idle-time=-1 --daemonize=yes 2>/dev/null || true
    sleep 1
fi

pactl load-module module-bluetooth-discover 2>/dev/null || true

mkdir -p /root/.voiceterm/wakewords
mkdir -p /opt/voiceterm/sounds

if [ ! -f /opt/voiceterm/sounds/beep.wav ]; then
    echo "[entrypoint] Генерация beep.wav..."
    python3 - << 'EOF'
import wave, struct, math
path = "/opt/voiceterm/sounds/beep.wav"
sr, freq, dur = 16000, 880, 0.2
n = int(sr * dur)
with wave.open(path, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    for i in range(n):
        s = int(32767 * math.sin(2*math.pi*freq*i/sr) * (1-i/n))
        w.writeframes(struct.pack("<h", s))
print(f"Создан: {path}")
EOF
fi

echo "[entrypoint] Готово. Запуск: $@"
echo "========================================"

exec "$@"
