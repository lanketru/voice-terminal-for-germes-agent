# 🎙 VoiceTerm

**Autonomous voice terminal for Raspberry Pi Zero 2 W** — listens for a wake word, records a voice command, sends it to [Hermes Agent](https://github.com/hermesagent), and plays back the response. Supports a Live mode for two-way audio streaming via Bluetooth headset.

## Features

- 🔍 **Wake word detection** — local, offline (EfficientWord-Net)
- 🎤 **Voice recording** — PyAudio with automatic silence detection (RMS)
- 🤖 **Hermes Agent integration** — WebSocket with auto-reconnect and keepalive
- 📡 **Live mode** — two-way audio stream triggered by BT headset button
- 🔊 **Bluetooth & built-in audio** — selectable via web interface
- 🌐 **Web setup interface** — WiFi AP on first boot, captive portal
- ⚙️ **Wake word training** — record 4–5 samples right in the browser
- 🔄 **Auto-start** — systemd service

## Quick Start

```bash
git clone https://github.com/lanketru/voice-terminal-for-germes-agent.git /opt/voiceterm
cd /opt/voiceterm
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
sudo python3 main.py
```

Connect to the **VoiceTerm** WiFi network → open a browser → configure WiFi, audio, wake word and Hermes URL.

## Docker

```bash
docker compose up --build -d
docker compose logs -f
```

> Requires `privileged: true` and `network_mode: host`.

## License

MIT License

---
---

# 🎙 VoiceTerm (Русский / Russian)

**Автономный голосовой терминал для Raspberry Pi Zero 2 W** — работает как умная колонка: слушает ключевое слово, записывает команду, отправляет в [Hermes Agent](https://github.com/hermesagent) и воспроизводит ответ. Поддерживает Live-режим двустороннего аудиопотока через Bluetooth-гарнитуру.

---

## Возможности

- 🔍 **Обнаружение ключевого слова** — локально, без интернета (EfficientWord-Net)
- 🎤 **Запись команды** — PyAudio с автоматическим детектом тишины по RMS
- 🤖 **Интеграция с Hermes Agent** — WebSocket с автореконнектом и keepalive
- 📡 **Live-режим** — двусторонний аудиопоток по нажатию кнопки BT-гарнитуры
- 🔊 **Bluetooth и встроенная аудиокарта** — выбор и настройка через веб-интерфейс
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
[Beep-сигнал]  →  [PyAudio запись до тишины]
        ↓
[faster-whisper STT → текст]   ← опционально
        ↓
[WebSocket → Hermes Agent]
        ↓
[Аудио-ответ → воспроизведение]

────────────────────────────────
Параллельно (BT-гарнитура):
[Кнопка «Ответить»] → [Live-сессия: двусторонний PCM-поток ↔ Hermes]
[Кнопка «Завершить»] → [Стоп сессии]
```

---

## Структура проекта

```
/opt/voiceterm/
├── main.py                  # Точка входа, выбор режима
├── config.py                # Загрузка/сохранение config.json
├── hotword_listener.py      # EfficientWord-Net интеграция
├── audio_recorder.py        # PyAudio запись с детектом тишины
├── hermes_client.py         # WebSocket клиент с автореконнектом
├── audio_player.py          # Воспроизведение WAV/аудио
├── bluetooth_manager.py     # bluetoothctl обёртка
├── bt_live_mode.py          # Live-режим через кнопку BT-гарнитуры
├── requirements.txt
├── setup_server/
│   ├── app.py               # Flask веб-сервер настроек
│   ├── wifi_manager.py      # nmcli обёртка
│   └── templates/
│       └── index.html       # Веб-интерфейс настроек
├── systemd/
│   └── voiceterm.service    # Автозапуск
└── scripts/
    └── setup_ap.sh          # hostapd + dnsmasq + captive portal
```

---

## Требования

### Оборудование

- Raspberry Pi Zero 2 W (или любой Pi с WiFi)
- Микрофон (USB, I2S, или встроенный в BT-гарнитуру)
- Динамик или Bluetooth-гарнитура/колонка

### Программные зависимости

**Python 3.10–3.14:**

```
EfficientWord-Net
pyaudio
sounddevice
numpy
websockets
faster-whisper
flask
flask-cors
evdev
```

**Системные пакеты (apt):**

```
portaudio19-dev
libopus0
ffmpeg
hostapd
dnsmasq
bluez
pulseaudio-module-bluetooth
python3-evdev
```

---

## Установка

### 1. Системные зависимости

```bash
sudo apt-get update
sudo apt-get install -y \
    portaudio19-dev libopus0 ffmpeg \
    hostapd dnsmasq bluez \
    pulseaudio-module-bluetooth \
    python3-evdev python3-pip python3-venv
```

### 2. Клонирование репозитория

```bash
sudo mkdir -p /opt/voiceterm
sudo chown $USER:$USER /opt/voiceterm
git clone https://github.com/your-org/voiceterm.git /opt/voiceterm
cd /opt/voiceterm
```

### 3. Виртуальное окружение и Python-пакеты

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> **Примечание:** Установка `EfficientWord-Net` загрузит модель `Resnet50_Arc_loss` (~88 МБ) при первом запуске.

### 4. Права для доступа к аудио и Bluetooth

```bash
sudo usermod -aG audio,bluetooth,input $USER
```

### 5. Установка systemd-сервиса

```bash
sudo cp systemd/voiceterm.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable voiceterm
```

---

## Первоначальная настройка

При первом запуске (или если `~/.voiceterm/config.json` отсутствует) терминал автоматически:

1. Поднимает WiFi-точку доступа с именем **`VoiceTerm`** (без пароля)
2. Запускает веб-сервер настроек на `http://192.168.4.1:8080`

```bash
sudo python3 /opt/voiceterm/main.py
# или через systemd:
sudo systemctl start voiceterm
```

**Подключитесь к WiFi-сети `VoiceTerm`** и откройте браузер — вас автоматически перенаправит на страницу настроек.

### Разделы настроек

| Раздел | Описание |
|--------|----------|
| **WiFi** | Поиск и подключение к домашней сети |
| **Аудиоканал** | Выбор встроенной карты или Bluetooth |
| **Проверка аудио** | Тест воспроизведения и микрофона |
| **Ключевое слово** | Запись 4–5 образцов и генерация модели |
| **Hermes Agent** | Ввод WebSocket URL и проверка соединения |
| **Системные настройки** | Пороги, тайминги, модель STT |

После нажатия **«Сохранить и запустить»** точка доступа выключается, устройство подключается к домашней WiFi и запускается в рабочем режиме.

---

## Конфигурация

Файл конфигурации хранится в `~/.voiceterm/config.json`:

```json
{
  "setup_complete": true,
  "wakeword": "компьютер",
  "reference_file_path": "/home/pi/.voiceterm/wakewords/компьютер_ref.json",
  "hotword_threshold": 0.8,
  "relaxation_time": 2.0,
  "window_length_secs": 1.5,
  "sliding_window_secs": 0.75,
  "audio_channel": "bluetooth",
  "audio_device_index": null,
  "bluetooth_mac": "AA:BB:CC:DD:EE:FF",
  "silence_threshold_rms": 200,
  "silence_duration_ms": 1500,
  "beep_enabled": true,
  "beep_wav_path": "/opt/voiceterm/sounds/beep.wav",
  "hermes_url": "ws://192.168.1.100:8765",
  "stt_model": "base",
  "reconnect_interval_sec": 1,
  "live_mode_enabled": true,
  "live_chunk_frames": 1024,
  "live_samplerate": 16000
}
```

### Параметры

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `hotword_threshold` | `0.8` | Порог уверенности (0.0–1.0) |
| `relaxation_time` | `2.0` | Мин. интервал между срабатываниями (сек) |
| `silence_threshold_rms` | `200` | Порог тишины для остановки записи |
| `silence_duration_ms` | `1500` | Длительность тишины для остановки (мс) |
| `stt_model` | `base` | Модель Whisper: `tiny` / `base` / `small` |
| `live_mode_enabled` | `true` | Включить Live-режим через BT-гарнитуру |
| `live_chunk_frames` | `1024` | Размер аудиочанка для Live-потока |

---

## Live-режим (Bluetooth-гарнитура)

При нажатии кнопки **«Ответить»** на Bluetooth-гарнитуре терминал входит в режим живого диалога:

- 🎤 Микрофон гарнитуры → потоковый PCM → Hermes Agent
- 🔊 Аудио-ответ от Hermes → динамик гарнитуры в реальном времени
- Hotword-обнаружение **приостанавливается** на время Live-сессии

**Завершение:** повторное нажатие кнопки «Ответить» или нажатие кнопки «Завершить вызов».

### Протокол Live-сессии

```
→ {"type": "live_start", "samplerate": 16000, "channels": 1}
→ <бинарный PCM int16 чанк> × N
→ {"type": "live_stop"}

← <бинарный PCM/WAV чанк> × N  (аудио-ответ Hermes)
```

### Поддерживаемые кнопки (evdev)

| Кнопка | Коды |
|--------|------|
| Ответить / начать Live | `KEY_PHONE` (200), `KEY_MEDIA` (226), `KEY_PLAYPAUSE` (164) |
| Завершить / остановить Live | `KEY_PHONE` (200), `KEY_PHONE_HANGUP` (207) |

---

## Интеграция с Hermes Agent

Терминал подключается к Hermes Agent по WebSocket и ожидает:

- **Входящие данные:** бинарный WAV-файл или base64-encoded WAV — воспроизводится немедленно
- **Исходящие данные:** бинарный WAV с записанной командой пользователя

В Live-режиме используется потоковый PCM (без WAV-обёртки).

Пример сигнала подключения в настройках: `ws://192.168.1.100:8765`

---

## 🐳 Запуск в Docker

> **Важно:** Docker-контейнер требует привилегированного режима (`privileged: true`) и `network_mode: host` для корректной работы WiFi AP, Bluetooth и evdev.

### Быстрый старт

```bash
# Сборка и запуск
docker compose up --build -d

# Логи
docker compose logs -f

# Остановка
docker compose down
```

### Структура файлов

```
├── Dockerfile               # Двухстадийная сборка образа
├── docker-compose.yml       # Сервисная конфигурация
├── .dockerignore            # Исключения из контекста сборки
└── docker/
    └── entrypoint.sh        # Инициализация dbus, BT, PulseAudio
```

### Что делает entrypoint.sh

При каждом старте контейнера автоматически:
1. Запускает `dbus-daemon` (нужен для `bluetoothctl`)
2. Запускает `bluetoothd`
3. Подключает PulseAudio BT-модуль
4. Генерирует `sounds/beep.wav` если файл отсутствует

### Тома (volumes)

| Volume | Назначение |
|--------|-----------|
| `voiceterm_config` | `~/.voiceterm/` — конфиг и wakeword-модели (персистентный) |
| `/var/run/dbus` | D-Bus сокет хоста → bluetoothctl внутри контейнера |
| `/run/user/1000/pulse` | PulseAudio сокет хоста (опционально) |
| `./sounds` | WAV-файлы (beep и др.) |

### Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `PULSE_SERVER` | `unix:/run/user/1000/pulse/native` | PulseAudio сервер |
| `TZ` | `Europe/Moscow` | Часовой пояс |

### Сброс настроек в Docker

```bash
docker compose down
docker volume rm voiceterm_voiceterm_config
docker compose up -d
```

---

## Сброс настроек

Для повторного запуска мастера настроек удалите конфиг:

```bash
rm ~/.voiceterm/config.json
sudo systemctl restart voiceterm
```

---

## Лицензия

MIT License — см. [LICENSE](LICENSE).

---

## Благодарности

- [EfficientWord-Net](https://github.com/Ant-Brain/EfficientWord-Net) — локальное обнаружение ключевых слов
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — локальный STT
- [websockets](https://github.com/python-websockets/websockets) — WebSocket-клиент
