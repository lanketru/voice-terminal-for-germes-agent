"""
bt_live_mode.py — Live-режим двустороннего аудиопотока через BT-гарнитуру
"""

import asyncio
import json
import logging
import threading
from typing import Callable, Optional

import pyaudio
import sounddevice as sd
import numpy as np
import websockets

logger = logging.getLogger(__name__)

_ANSWER_KEYS = {200, 226, 0x8b, 164}
_HANGUP_KEYS = {200, 207}

CHUNK = 1024
SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16


def find_headset_input_device(headset_name: str = "", headset_mac: str = "") -> Optional[str]:
    try:
        import evdev
    except ImportError:
        logger.error("[live] evdev не установлен: pip install evdev")
        return None
    mac_norm = headset_mac.replace(":", "_").lower()
    name_lower = headset_name.lower()
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            dev_name = dev.name.lower()
            if (name_lower and name_lower in dev_name) or (mac_norm and mac_norm in dev_name):
                logger.info(f"[live] Гарнитура найдена: {dev.name} ({path})")
                return path
        except Exception:
            continue
    logger.warning("[live] Устройство гарнитуры не найдено")
    return None


class LiveSession:
    def __init__(self, ws_url: str, input_device_index=None, output_device_index=None,
                 chunk: int = CHUNK, samplerate: int = SAMPLE_RATE,
                 on_started=None, on_stopped=None):
        self.ws_url = ws_url
        self.input_device_index = input_device_index
        self.output_device_index = output_device_index
        self.chunk = chunk
        self.samplerate = samplerate
        self.on_started = on_started
        self.on_stopped = on_stopped
        self._active = False
        self._loop = None
        self._thread = None

    def start(self):
        if self._active:
            return
        self._active = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="LiveSession")
        self._thread.start()

    def stop(self):
        if not self._active:
            return
        self._active = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("[live] Сессия остановлена")
        if self.on_stopped:
            self.on_stopped()

    def is_active(self) -> bool:
        return self._active

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session())
        except Exception as e:
            logger.error(f"[live] Ошибка сессии: {e}")
        finally:
            self._loop.close()
            self._active = False
            if self.on_stopped:
                self.on_stopped()

    async def _session(self):
        logger.info(f"[live] Подключение к {self.ws_url}")
        try:
            async with websockets.connect(self.ws_url) as ws:
                await ws.send(json.dumps({"type": "live_start",
                                          "samplerate": self.samplerate, "channels": CHANNELS}))
                logger.info("[live] Сессия открыта")
                if self.on_started:
                    self.on_started()
                send_task = asyncio.ensure_future(self._sender(ws))
                recv_task = asyncio.ensure_future(self._receiver(ws))
                done, pending = await asyncio.wait([send_task, recv_task],
                                                   return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass
                try:
                    await ws.send(json.dumps({"type": "live_stop"}))
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[live] WebSocket ошибка: {e}")

    async def _sender(self, ws):
        pa = pyaudio.PyAudio()
        stream = pa.open(format=FORMAT, channels=CHANNELS, rate=self.samplerate,
                         input=True, input_device_index=self.input_device_index,
                         frames_per_buffer=self.chunk)
        loop = asyncio.get_event_loop()
        logger.info("[live] Микрофон запущен")
        try:
            while self._active:
                data = await loop.run_in_executor(
                    None, lambda: stream.read(self.chunk, exception_on_overflow=False))
                if not self._active:
                    break
                await ws.send(data)
        except Exception as e:
            if self._active:
                logger.error(f"[live] Ошибка отправки: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    async def _receiver(self, ws):
        out_stream = sd.OutputStream(samplerate=self.samplerate, channels=CHANNELS,
                                      dtype="int16", device=self.output_device_index)
        out_stream.start()
        try:
            async for message in ws:
                if not self._active:
                    break
                if isinstance(message, bytes) and len(message) > 0:
                    out_stream.write(np.frombuffer(message, dtype=np.int16))
                elif isinstance(message, str):
                    try:
                        if json.loads(message).get("type") == "live_stop":
                            break
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            if self._active:
                logger.error(f"[live] Ошибка приёма: {e}")
        finally:
            out_stream.stop()
            out_stream.close()


class BTButtonMonitor:
    def __init__(self, device_path: str, on_answer: Callable, on_hangup: Callable):
        self.device_path = device_path
        self.on_answer = on_answer
        self.on_hangup = on_hangup
        self._running = False
        self._in_call = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="BTButtonMonitor")
        self._thread.start()
        logger.info(f"[live] Мониторинг кнопок: {self.device_path}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)

    def _monitor_loop(self):
        try:
            import evdev
            dev = evdev.InputDevice(self.device_path)
            dev.grab()
        except Exception as e:
            logger.error(f"[live] Не удалось открыть устройство: {e}")
            self._running = False
            return
        try:
            for event in dev.read_loop():
                if not self._running:
                    break
                if event.type != 1 or event.value != 1:
                    continue
                code = event.code
                if not self._in_call and code in _ANSWER_KEYS:
                    self._in_call = True
                    logger.info("[live] Live-режим ON")
                    try:
                        self.on_answer()
                    except Exception as e:
                        logger.error(f"[live] on_answer ошибка: {e}")
                elif self._in_call and (code in _HANGUP_KEYS or code in _ANSWER_KEYS):
                    self._in_call = False
                    logger.info("[live] Live-режим OFF")
                    try:
                        self.on_hangup()
                    except Exception as e:
                        logger.error(f"[live] on_hangup ошибка: {e}")
        except Exception as e:
            if self._running:
                logger.error(f"[live] Ошибка чтения evdev: {e}")
        finally:
            try:
                dev.ungrab()
            except Exception:
                pass


class LiveModeController:
    def __init__(self, config: dict, ws_url: str,
                 on_live_start=None, on_live_stop=None):
        self.config = config
        self.ws_url = ws_url
        self.on_live_start = on_live_start
        self.on_live_stop = on_live_stop
        self._session = None
        self._monitor = None

    def setup(self) -> bool:
        if not self.config.get("live_mode_enabled", True):
            return False
        if self.config.get("audio_channel") != "bluetooth":
            return False
        headset_mac = self.config.get("bluetooth_mac", "")
        device_path = find_headset_input_device(headset_mac=headset_mac)
        if not device_path:
            logger.warning("[live] BT-гарнитура не найдена, Live-режим недоступен")
            return False
        self._monitor = BTButtonMonitor(
            device_path=device_path, on_answer=self._on_answer, on_hangup=self._on_hangup)
        self._monitor.start()
        logger.info("[live] LiveModeController готов")
        return True

    def shutdown(self):
        if self._monitor:
            self._monitor.stop()
        if self._session and self._session.is_active():
            self._session.stop()

    def _on_answer(self):
        if self.on_live_start:
            self.on_live_start()
        self._session = LiveSession(
            ws_url=self.ws_url,
            input_device_index=self.config.get("audio_device_index"),
            output_device_index=self.config.get("audio_device_index"),
            chunk=self.config.get("live_chunk_frames", CHUNK),
            samplerate=self.config.get("live_samplerate", SAMPLE_RATE),
            on_started=lambda: logger.info("[live] ▶ Live-сессия активна"),
            on_stopped=self._on_session_stopped)
        self._session.start()

    def _on_hangup(self):
        if self._session and self._session.is_active():
            self._session.stop()

    def _on_session_stopped(self):
        if self.on_live_stop:
            self.on_live_stop()
        if self._monitor:
            self._monitor._in_call = False
