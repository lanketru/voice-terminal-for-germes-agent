"""
audio_recorder.py — Запись аудио через PyAudio с детектом тишины по RMS
"""

import wave
import struct
import math
import logging
import time
import tempfile
import os
from pathlib import Path

import pyaudio

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024


def _calc_rms(data: bytes) -> float:
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    sum_sq = sum(s * s for s in shorts)
    return math.sqrt(sum_sq / count)


class AudioRecorder:
    """Запись аудио с детектом тишины."""

    def __init__(self, silence_threshold: int = 200, silence_duration_ms: int = 1500,
                 max_duration_sec: int = 30, device_index: int = None,
                 sample_rate: int = SAMPLE_RATE):
        self.silence_threshold = silence_threshold
        self.silence_duration_ms = silence_duration_ms
        self.max_duration_sec = max_duration_sec
        self.device_index = device_index
        self.sample_rate = sample_rate

    def record_until_silence(self, output_path: str = None) -> str:
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="voiceterm_")
            os.close(fd)

        pa = pyaudio.PyAudio()
        stream = None
        try:
            stream = pa.open(format=FORMAT, channels=CHANNELS, rate=self.sample_rate,
                             input=True, input_device_index=self.device_index,
                             frames_per_buffer=CHUNK)
            logger.info("[recorder] Запись начата")
            frames = []
            silence_chunks_needed = int((self.silence_duration_ms / 1000.0) * self.sample_rate / CHUNK)
            silent_chunks = 0
            max_chunks = int(self.max_duration_sec * self.sample_rate / CHUNK)
            total_chunks = 0

            while total_chunks < max_chunks:
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
                total_chunks += 1
                rms = _calc_rms(data)
                if rms < self.silence_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0
                if silent_chunks >= silence_chunks_needed:
                    logger.info(f"[recorder] Обнаружена тишина после {total_chunks} чанков")
                    break
            else:
                logger.warning(f"[recorder] Достигнут максимальный лимит {self.max_duration_sec}с")
        finally:
            if stream is not None:
                stream.stop_stream()
                stream.close()
            pa.terminate()

        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(pa.get_sample_size(FORMAT))
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"".join(frames))

        logger.info(f"[recorder] Сохранено: {output_path}")
        return output_path

    def record_fixed_duration(self, duration_sec: float, output_path: str = None) -> str:
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="voiceterm_sample_")
            os.close(fd)

        pa = pyaudio.PyAudio()
        stream = None
        try:
            stream = pa.open(format=FORMAT, channels=CHANNELS, rate=self.sample_rate,
                             input=True, input_device_index=self.device_index,
                             frames_per_buffer=CHUNK)
            logger.info(f"[recorder] Фиксированная запись {duration_sec}с")
            num_chunks = int(duration_sec * self.sample_rate / CHUNK)
            frames = []
            for _ in range(num_chunks):
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
        finally:
            if stream is not None:
                stream.stop_stream()
                stream.close()
            pa.terminate()

        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(pa.get_sample_size(FORMAT))
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"".join(frames))

        logger.info(f"[recorder] Сохранено: {output_path}")
        return output_path
