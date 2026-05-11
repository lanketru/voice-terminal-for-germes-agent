"""
bt_live_mode.py — Live mode for two-way audio streaming via BT headset.
                   Live-режим двустороннего аудиопотока через BT-гарнитуру.

Logic / Логика:
  1. BTButtonMonitor finds evdev device of headset and listens for button presses.
  2. On "Answer" press → starts LiveSession.
  3. LiveSession opens two-way audio stream with Hermes Agent via WebSocket.
  4. On second "Answer" or "Hang up" press → stops the session.
"""

import asyncio
import json
import logging
import threading
import time
from typing import Callable, Optional

import pyaudio
import sounddevice as sd
import numpy as np
import websockets

logger = logging.getLogger(__name__)

# Коды кнопок гарнитуры (linux/input-event-codes.h)
_ANSWER_KEYS = {
    200,   # KEY_PHONE
    226,   # KEY_MEDIA
    0x8b,  # KEY_MENU — некоторые гарнитуры
    164,   # KEY_PLAYPAUSE — некоторые модели
}
_HANGUP_KEYS = {
    200,   # KEY_PHONE (повторное нажатие = завершить)
    207,   # KEY_PHONE_HANGUP
}

CHUNK = 1024
SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16


# ─────────────────────────────────────────────────────────────────────────────
# Find headset evdev device / Поиск evdev-устройства гарнитуры
# ─────────────────────────────────────────────────────────────────────────────

def find_headset_input_device(headset_name: str = "", headset_mac: str = "") -> Optional[str]:
    """
    Найти путь к evdev-устройству Bluetooth-гарнитуры.

    Сканирует /dev/input/event* и возвращает путь к первому устройству,
    в имени которого содержится headset_name или нормализованный headset_mac.

    Args:
        headset_name: Имя устройства (из bluetoothctl).
        headset_mac:  MAC-адрес вида AA:BB:CC:DD:EE:FF.

    Returns:
        Путь к устройству или None если не найдено.
    """
    try:
        import evdev
    except ImportError:
        logger.error("[live] evdev не установлен: pip install evdev")
        return None

    mac_norm = headset_mac.replace(":", "_").replace(":", "-").lower()
    name_lower = headset_name.lower()

    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            dev_name = dev.name.lower()
            if (name_lower and name_lower in dev_name) or \
               (mac_norm and mac_norm in dev_name):
                logger.info(f"[live] Гарнитура найдена: {dev.name} ({path})")
                return path
        except Exception:
            continue
    logger.warning("[live] Устройство гарнитуры не найдено в /dev/input/")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Live-сессия (двусторонний аудиопоток)
# ─────────────────────────────────────────────────────────────────────────────

class LiveSession:
    """
    Двусторонняя Live-сессия с Hermes Agent.

    - Захватывает микрофон чанками CHUNK×int16 и отправляет по WebSocket.
    - Принимает бинарные фреймы и воспроизводит через sounddevice.
    - Завершается через stop().
    """

    def __init__(
        self,
        ws_url: str,
        input_device_index: Optional[int] = None,
        output_device_index: Optional[int] = None,
        chunk: int = CHUNK,
        samplerate: int = SAMPLE_RATE,
        on_started: Optional[Callable] = None,
        on_stopped: Optional[Callable] = None,
    ):
        self.ws_url = ws_url
        self.input_device_index = input_device_index
        self.output_device_index = output_device_index
        self.chunk = chunk
        self.samplerate = samplerate
        self.on_started = on_started
        self.on_stopped = on_stopped

        self._active = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    # ── Публичный интерфейс ──────────────────────────────────────────────────

    def start(self):
        """Запустить Live-сессию в фоновом потоке."""
        if self._active:
            logger.warning("[live] Сессия уже запущена")
            return
        self._active = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="LiveSession"
        )
        self._thread.start()

    def stop(self):
        """Остановить Live-сессию."""
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

    # ── Реализация ──────────────────────────────────────────────────────────

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
        """Открыть WebSocket и запустить параллельные задачи отправки и приёма."""
        logger.info(f"[live] Подключение к {self.ws_url}")
        try:
            async with websockets.connect(self.ws_url) as ws:
                # Сигнал старта
                await ws.send(json.dumps({
                    "type": "live_start",
                    "samplerate": self.samplerate,
                    "channels": CHANNELS,
                }))
                logger.info("[live] Сессия открыта")
                if self.on_started:
                    self.on_started()

                send_task = asyncio.ensure_future(self._sender(ws))
                recv_task = asyncio.ensure_future(self._receiver(ws))

                done, pending = await asyncio.wait(
                    [send_task, recv_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass

                # Сигнал завершения
                try:
                    await ws.send(json.dumps({"type": "live_stop"}))
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"[live] WebSocket ошибка: {e}")

    async def _sender(self, ws):
        """Захват микрофона и отправка PCM-чанков."""
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=self.samplerate,
            input=True,
            input_device_index=self.input_device_index,
            frames_per_buffer=self.chunk,
        )
        loop = asyncio.get_event_loop()
        logger.info("[live] Микрофон запущен")
        try:
            while self._active:
                # Читаем чанк в executor чтобы не блокировать event loop
                data = await loop.run_in_executor(
                    None, lambda: stream.read(self.chunk, exception_on_overflow=False)
                )
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
        """Приём аудио от Hermes и воспроизведение."""
        # Открываем output stream sounddevice
        out_stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=CHANNELS,
            dtype="int16",
            device=self.output_device_index,
        )
        out_stream.start()
        logger.info("[live] Вывод звука запущен")
        try:
            async for message in ws:
                if not self._active:
                    break
                if isinstance(message, bytes) and len(message) > 0:
                    audio = np.frombuffer(message, dtype=np.int16)
                    out_stream.write(audio)
                elif isinstance(message, str):
                    try:
                        msg = json.loads(message)
                        if msg.get("type") == "live_stop":
                            logger.info("[live] Hermes завершил сессию")
                            break
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            if self._active:
                logger.error(f"[live] Ошибка приёма: {e}")
        finally:
            out_stream.stop()
            out_stream.close()


# ─────────────────────────────────────────────────────────────────────────────
# Монитор кнопки BT-гарнитуры
# ─────────────────────────────────────────────────────────────────────────────

class BTButtonMonitor:
    """
    Мониторинг кнопок Bluetooth-гарнитуры через evdev.

    Логика переключения:
    - Первое нажатие answer/call-кнопки → on_answer()
    - Повторное нажатие или нажатие hangup-кнопки → on_hangup()
    """

    def __init__(
        self,
        device_path: str,
        on_answer: Callable,
        on_hangup: Callable,
    ):
        """
        Args:
            device_path: Путь к evdev-устройству (/dev/input/eventN).
            on_answer: Callback при нажатии «Ответить».
            on_hangup: Callback при нажатии «Завершить».
        """
        self.device_path = device_path
        self.on_answer = on_answer
        self.on_hangup = on_hangup

        self._running = False
        self._in_call = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Запустить мониторинг в фоновом потоке."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="BTButtonMonitor"
        )
        self._thread.start()
        logger.info(f"[live] Мониторинг кнопок: {self.device_path}")

    def stop(self):
        """Остановить мониторинг."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)

    def _monitor_loop(self):
        try:
            import evdev
            dev = evdev.InputDevice(self.device_path)
            dev.grab()  # Эксклюзивный доступ
        except Exception as e:
            logger.error(f"[live] Не удалось открыть устройство: {e}")
            self._running = False
            return

        try:
            for event in dev.read_loop():
                if not self._running:
                    break
                # Ожидаем только key-события с нажатием (value=1)
                if event.type != 1:  # EV_KEY = 1
                    continue
                if event.value != 1:  # 1 = нажатие, 0 = отпускание, 2 = удержание
                    continue

                code = event.code
                logger.debug(f"[live] Кнопка: code={code}")

                if not self._in_call and code in _ANSWER_KEYS:
                    self._in_call = True
                    logger.info("[live] Нажата «Ответить» → Live-режим ON")
                    try:
                        self.on_answer()
                    except Exception as e:
                        logger.error(f"[live] on_answer ошибка: {e}")

                elif self._in_call and (code in _HANGUP_KEYS or code in _ANSWER_KEYS):
                    self._in_call = False
                    logger.info("[live] Нажата «Завершить» → Live-режим OFF")
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


# ─────────────────────────────────────────────────────────────────────────────
# Фасад: LiveModeController
# ─────────────────────────────────────────────────────────────────────────────

class LiveModeController:
    """
    Высокоуровневый контроллер Live-режима.

    Объединяет BTButtonMonitor + LiveSession.
    Приостанавливает hotword-прослушивание на время Live-сессии.
    """

    def __init__(
        self,
        config: dict,
        ws_url: str,
        on_live_start: Optional[Callable] = None,
        on_live_stop: Optional[Callable] = None,
    ):
        """
        Args:
            config: Конфиг VoiceTerm.
            ws_url: WebSocket URL Hermes Agent.
            on_live_start: Callback при входе в Live-режим (для паузы hotword).
            on_live_stop: Callback при выходе из Live-режима (для возобновления hotword).
        """
        self.config = config
        self.ws_url = ws_url
        self.on_live_start = on_live_start
        self.on_live_stop = on_live_stop

        self._session: Optional[LiveSession] = None
        self._monitor: Optional[BTButtonMonitor] = None

    def setup(self) -> bool:
        """
        Найти BT-гарнитуру и запустить мониторинг кнопок.

        Returns:
            True если устройство найдено и мониторинг запущен.
        """
        if not self.config.get("live_mode_enabled", True):
            return False
        if self.config.get("audio_channel") != "bluetooth":
            logger.info("[live] Live-режим доступен только при Bluetooth-канале")
            return False

        headset_mac = self.config.get("bluetooth_mac", "")
        device_path = find_headset_input_device(headset_mac=headset_mac)

        if not device_path:
            logger.warning("[live] BT-гарнитура не найдена, Live-режим недоступен")
            return False

        self._monitor = BTButtonMonitor(
            device_path=device_path,
            on_answer=self._on_answer,
            on_hangup=self._on_hangup,
        )
        self._monitor.start()
        logger.info("[live] LiveModeController готов")
        return True

    def shutdown(self):
        """Остановить всё."""
        if self._monitor:
            self._monitor.stop()
        if self._session and self._session.is_active():
            self._session.stop()

    def _on_answer(self):
        """Запустить Live-сессию."""
        if self.on_live_start:
            self.on_live_start()  # Пауза hotword

        self._session = LiveSession(
            ws_url=self.ws_url,
            input_device_index=self.config.get("audio_device_index"),
            output_device_index=self.config.get("audio_device_index"),
            chunk=self.config.get("live_chunk_frames", CHUNK),
            samplerate=self.config.get("live_samplerate", SAMPLE_RATE),
            on_started=lambda: logger.info("[live] ▶ Live-сессия активна"),
            on_stopped=self._on_session_stopped,
        )
        self._session.start()

    def _on_hangup(self):
        """Остановить Live-сессию."""
        if self._session and self._session.is_active():
            self._session.stop()

    def _on_session_stopped(self):
        """Вызывается когда сессия завершилась (в т.ч. по ошибке)."""
        if self.on_live_stop:
            self.on_live_stop()  # Возобновить hotword
        # Сбросить флаг in_call в мониторе
        if self._monitor:
            self._monitor._in_call = False
