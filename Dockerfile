# ── Стадия 1: сборка зависимостей ────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    portaudio19-dev \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Стадия 2: рабочий образ ──────────────────────────────────────────────
FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="VoiceTerm"
LABEL org.opencontainers.image.description="Голосовой терминал для Hermes Agent"
LABEL org.opencontainers.image.source="https://github.com/lanketru/voice-terminal-for-germes-agent"

RUN apt-get update && apt-get install -y --no-install-recommends \
    portaudio19-dev libportaudio2 alsa-utils pulseaudio-utils \
    libsndfile1 ffmpeg bluez bluez-tools \
    hostapd dnsmasq iproute2 iptables network-manager \
    python3-evdev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /opt/voiceterm
COPY . .

RUN mkdir -p /root/.voiceterm/wakewords /opt/voiceterm/sounds
RUN chmod +x /opt/voiceterm/docker/entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/opt/voiceterm/docker/entrypoint.sh"]
CMD ["python", "main.py"]
