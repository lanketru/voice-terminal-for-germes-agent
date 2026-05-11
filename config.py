"""
config.py — Load and save VoiceTerm configuration.
             Загрузка и сохранение конфигурации VoiceTerm.
"""

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".voiceterm"
CONFIG_FILE = CONFIG_DIR / "config.json"
WAKEWORDS_DIR = CONFIG_DIR / "wakewords"
SOUNDS_DIR = Path("/opt/voiceterm/sounds")

DEFAULT_CONFIG = {
    "setup_complete": False,
    "wakeword": "",
    "reference_file_path": "",
    "hotword_threshold": 0.8,
    "relaxation_time": 2.0,
    "window_length_secs": 1.5,
    "sliding_window_secs": 0.75,
    "audio_channel": "builtin",
    "audio_device_index": None,
    "bluetooth_mac": "",
    "silence_threshold_rms": 200,
    "silence_duration_ms": 1500,
    "beep_enabled": True,
    "beep_wav_path": str(SOUNDS_DIR / "beep.wav"),
    "hermes_url": "ws://192.168.1.100:8765",
    "stt_model": "base",
    "reconnect_interval_sec": 1
}


def ensure_dirs():  # Create necessary directories if missing
    """Create necessary directories if they don't exist. / Создать необходимые директории."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    WAKEWORDS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:  # Load configuration from file
    """Load config from file; return defaults if missing. / Загрузить конфиг из файла; вернуть дефолт если отсутствует."""
    ensure_dirs()
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Fill missing keys from default / Дополнить новыми ключами из дефолта если отсутствуют
        for key, value in DEFAULT_CONFIG.items():
            data.setdefault(key, value)
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"[config] Config read error / Ошибка чтения конфига: {e}, using default / использую дефолт")
        return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> bool:  # Save configuration to file
    """Save config to file. Returns True on success. / Сохранить конфиг в файл. True при успехе."""
    ensure_dirs()
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"[config] Config save error / Ошибка сохранения конфига: {e}")
        return False


def is_setup_complete() -> bool:  # Check if initial setup is complete
    """Check if initial setup has been completed. / Проверить, завершена ли первоначальная настройка."""
    config = load_config()
    return bool(config.get("setup_complete", False))
