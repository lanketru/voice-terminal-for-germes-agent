"""
audio_player.py — WAV/audio playback via PyAudio or sounddevice.
                   Воспроизведение WAV/аудио через PyAudio или sounddevice.
"""

import wave
import threading
import logging
import os
import io

import pyaudio
import sounddevice as sd
import numpy as np

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Воспроизведение аудио на выбранном устройстве."""

    def __init__(self, device_index: int = None):
        """
        Args:
            device_index: Индекс устройства вывода sounddevice.
                          None = системное устройство по умолчанию.
        """
        self.device_index = device_index
        self._lock = threading.Lock()

    def play_wav_file(self, wav_path: str, block: bool = True) -> bool:
        """
        Воспроизвести WAV-файл.

        Args:
            wav_path: Путь к WAV-файлу.
            block: Если True — ждать окончания воспроизведения.

        Returns:
            True при успешном воспроизведении.
        """
        if not os.path.exists(wav_path):
            logger.error(f"[player] Файл не найден: {wav_path}")
            return False

        def _play():
            with self._lock:
                try:
                    with wave.open(wav_path, "rb") as wf:
                        channels = wf.getnchannels()
                        sampwidth = wf.getsampwidth()
                        framerate = wf.getframerate()
                        frames = wf.readframes(wf.getnframes())

                    dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
                    dtype = dtype_map.get(sampwidth, np.int16)
                    audio_data = np.frombuffer(frames, dtype=dtype)

                    if channels > 1:
                        audio_data = audio_data.reshape(-1, channels)

                    # Нормализация до float32 для sounddevice
                    max_val = float(np.iinfo(dtype).max)
                    audio_float = audio_data.astype(np.float32) / max_val

                    sd.play(audio_float, samplerate=framerate, device=self.device_index)
                    sd.wait()
                except Exception as e:
                    logger.error(f"[player] Ошибка воспроизведения: {e}")

        if block:
            _play()
            return True
        else:
            t = threading.Thread(target=_play, daemon=True)
            t.start()
            return True

    def play_wav_bytes(self, wav_bytes: bytes, block: bool = True) -> bool:
        """
        Воспроизвести аудио из байтов (WAV-формат).

        Args:
            wav_bytes: Байты WAV-данных.
            block: Если True — ждать окончания воспроизведения.

        Returns:
            True при успешном воспроизведении.
        """
        def _play():
            with self._lock:
                try:
                    buf = io.BytesIO(wav_bytes)
                    with wave.open(buf, "rb") as wf:
                        channels = wf.getnchannels()
                        sampwidth = wf.getsampwidth()
                        framerate = wf.getframerate()
                        frames = wf.readframes(wf.getnframes())

                    dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
                    dtype = dtype_map.get(sampwidth, np.int16)
                    audio_data = np.frombuffer(frames, dtype=dtype)

                    if channels > 1:
                        audio_data = audio_data.reshape(-1, channels)

                    max_val = float(np.iinfo(dtype).max)
                    audio_float = audio_data.astype(np.float32) / max_val

                    sd.play(audio_float, samplerate=framerate, device=self.device_index)
                    sd.wait()
                except Exception as e:
                    logger.error(f"[player] Ошибка воспроизведения из байтов: {e}")

        if block:
            _play()
            return True
        else:
            t = threading.Thread(target=_play, daemon=True)
            t.start()
            return True

    def stop(self):
        """Остановить текущее воспроизведение."""
        try:
            sd.stop()
        except Exception as e:
            logger.warning(f"[player] Ошибка остановки: {e}")


def list_output_devices() -> list:
    """
    Получить список доступных аудиоустройств вывода.

    Returns:
        Список словарей с ключами: index, name, max_output_channels, default_samplerate.
    """
    devices = []
    try:
        all_devices = sd.query_devices()
        for i, dev in enumerate(all_devices):
            if dev["max_output_channels"] > 0:
                devices.append({
                    "index": i,
                    "name": dev["name"],
                    "max_output_channels": dev["max_output_channels"],
                    "default_samplerate": int(dev["default_samplerate"])
                })
    except Exception as e:
        logger.error(f"[player] Ошибка получения устройств: {e}")
    return devices


def list_input_devices() -> list:
    """
    Получить список доступных аудиоустройств ввода (микрофонов).

    Returns:
        Список словарей с ключами: index, name, max_input_channels, default_samplerate.
    """
    devices = []
    try:
        all_devices = sd.query_devices()
        for i, dev in enumerate(all_devices):
            if dev["max_input_channels"] > 0:
                devices.append({
                    "index": i,
                    "name": dev["name"],
                    "max_input_channels": dev["max_input_channels"],
                    "default_samplerate": int(dev["default_samplerate"])
                })
    except Exception as e:
        logger.error(f"[player] Ошибка получения микрофонов: {e}")
    return devices
