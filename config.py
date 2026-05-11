"""
config.py — Загрузка и сохранение конфигурации VoiceTerm
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


def ensure_dirs():
    """Создать необходимые директории если отсутствуют."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    WAKEWORDS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Загрузить конфигурацию из файла. Если файл отсутствует — вернуть дефолт."""
    ensure_dirs()
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, value in DEFAULT_CONFIG.items():
            data.setdefault(key, value)
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"[config] Ошибка чтения конфига: {e}, использую дефолт")
        return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> bool:
    """Сохранить конфигурацию в файл. Возвращает True при успехе."""
    ensure_dirs()
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"[config] Ошибка сохранения конфига: {e}")
        return False


def is_setup_complete() -> bool:
    """Проверить, завершена ли первоначальная настройка."""
    config = load_config()
    return bool(config.get("setup_complete", False))
