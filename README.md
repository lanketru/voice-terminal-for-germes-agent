# 🎙 VoiceTerm

**Автономный голосовой терминал для Raspberry Pi Zero 2 W** — слушает ключевое слово, записывает команду, отправляет в Hermes Agent и воспроизводит ответ. Поддерживает Live-режим двустороннего аудиопотока через Bluetooth-гарнитуру.

---

## Возможности

- 🔍 **Обнаружение ключевого слова** — локально, без интернета (EfficientWord-Net)
- 🎙 **Запись команды** — PyAudio с автодетектом тишины по RMS
- 🤖 **Интеграция с Hermes Agent** — WebSocket с автореконнектом и keepalive
- 📡 **Live-режим** — двусторонний аудиопоток по нажатию кнопки BT-гарнитуры
- 🔊 **Bluetooth и встроенная аудиокарта** — выбор через веб-интерфейс
- 🌐 **Веб-интерфейс настроек** — WiFi AP при первом запуске, captive portal
- ⚙️ **Обучение wake word** — запись 4–5 образцов прямо в браузере
- 🔄 **Автозапуск** — systemd-сервис

---

## Архитектура

```
[Микрофон / BT-гарнитура]
        ↓
[EfficientWord-Net — обнаружение ключевого слова]
        ↓ (срабатывание)
[Beep-сигнал] → [PyAudio запись до тишины]
        ↓
[WebSocket → Hermes Agent]
        ↓
[Аудио-ответ → воспроизведение]

Параллельно (BT-гарнитура):
[Кнопка «Ответить»] → [Live-сессия: двусторонний PCM-поток ↔ Hermes]
```

---

## Структура проекта

```
/opt/voiceterm/
├── main.py                  # Точка входа
├── config.py                # Загрузка/сохранение config.json
├── hotword_listener.py      # EfficientWord-Net интеграция
├── audio_recorder.py        # PyAudio запись с детектом тишины
├── hermes_client.py         # WebSocket клиент
├── audio_player.py          # Воспроизведение WAV
├── bluetooth_manager.py     # bluetoothctl обёртка
├── bt_live_mode.py          # Live-режим через BT-гарнитуру
├── requirements.txt
├── setup_server/
│   ├── app.py               # Flask сервер настроек
│   ├── wifi_manager.py      # nmcli обёртка
│   └── templates/index.html # Веб-интерфейс
├── systemd/voiceterm.service
└── scripts/setup_ap.sh
```

---

## Установка

### 1. Системные зависимости

```bash
sudo apt-get update && sudo apt-get install -y \
    portaudio19-dev libopus0 ffmpeg \
    hostapd dnsmasq bluez \
    pulseaudio-module-bluetooth \
    python3-evdev python3-pip python3-venv
```

### 2. Клонирование репозитория

```bash
sudo mkdir -p /opt/voiceterm && sudo chown $USER:$USER /opt/voiceterm
git clone https://github.com/lanketru/voice-terminal-for-germes-agent.git /opt/voiceterm
cd /opt/voiceterm
```

### 3. Python-окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
```

### 4. Права доступа

```bash
sudo usermod -aG audio,bluetooth,input $USER
```

### 5. systemd-сервис

```bash
sudo cp systemd/voiceterm.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable voiceterm
```

---

## Первоначальная настройка

При первом запуске терминал автоматически поднимает WiFi-точку доступа **`VoiceTerm`** и запускает веб-сервер на `http://192.168.4.1:8080`.

Подключитесь к WiFi **`VoiceTerm`** → откройте браузер → настройте WiFi, аудио, ключевое слово и Hermes URL.

---

## 🐳 Docker

```bash
docker compose up --build -d
docker compose logs -f
```

> **Важно:** Требует `privileged: true` и `network_mode: host`.

---

## Протокол Live-сессии

```
→ {"type": "live_start", "samplerate": 16000, "channels": 1}
→ <бинарный PCM int16 чанк> × N
→ {"type": "live_stop"}
← <бинарный PCM/WAV чанк> × N
```

---

## Лицензия

MIT License

---

## Благодарности

- [EfficientWord-Net](https://github.com/Ant-Brain/EfficientWord-Net)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [websockets](https://github.com/python-websockets/websockets)
