"""
hermes_client.py — WebSocket client for Hermes Agent with auto-reconnect.
                    WebSocket-клиент для Hermes Agent с автореконнектом.
"""

import asyncio
import base64
import logging
import threading
import time
from typing import Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class HermesClient:
    """
    Асинхронный WebSocket-клиент для Hermes Agent.

    Функции:
    - Постоянное соединение с автореконнектом
    - Отправка WAV-аудио (бинарный фрейм или base64)
    - Получение аудио-ответа и вызов callback
    - Keepalive пинг каждые 30 секунд
    - Экспоненциальный backoff (до 5 секунд)
    """

    PING_INTERVAL = 30  # секунд
    MAX_RECONNECT_INTERVAL = 5  # секунд

    def __init__(
        self,
        url: str,
        reconnect_interval_sec: float = 1.0,
        on_audio_response: Optional[Callable[[bytes], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            url: WebSocket URL Hermes Agent (например: ws://192.168.1.100:8765).
            reconnect_interval_sec: Начальный интервал реконнекта в секундах.
            on_audio_response: Callback при получении аудио-ответа (bytes WAV).
            on_connect: Callback при успешном подключении.
            on_disconnect: Callback при отключении.
        """
        self.url = url
        self.reconnect_interval_sec = reconnect_interval_sec
        self.on_audio_response = on_audio_response
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._connected = False
        self._send_queue: Optional[asyncio.Queue] = None

    # ------------------------------------------------------------------
    # Публичный интерфейс (потокобезопасный)
    # ------------------------------------------------------------------

    def start(self):
        """Запустить клиент в фоновом потоке."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_event_loop, daemon=True, name="HermesClient"
        )
        self._thread.start()

    def stop(self):
        """Остановить клиент."""
        self._running = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5.0)
            logger.info("[hermes] Клиент остановлен")

    def send_audio(self, wav_bytes: bytes):
        """
        Отправить WAV-аудио в Hermes Agent (потокобезопасно).

        Args:
            wav_bytes: Байты WAV-файла.
        """
        if self._loop and self._send_queue and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                self._send_queue.put_nowait, wav_bytes
            )
        else:
            logger.warning("[hermes] Нет соединения, аудио не отправлено")

    def is_connected(self) -> bool:
        """Проверить, установлено ли соединение."""
        return self._connected

    def check_connection(self, timeout: float = 5.0) -> bool:
        """
        Синхронная проверка WebSocket-соединения.

        Args:
            timeout: Таймаут проверки в секундах.

        Returns:
            True если соединение успешно установлено.
        """
        result = {"ok": False}
        event = threading.Event()

        async def _check():
            try:
                async with websockets.connect(self.url, open_timeout=timeout) as ws:
                    result["ok"] = True
            except Exception as e:
                logger.warning(f"[hermes] Проверка соединения: {e}")
            finally:
                event.set()

        loop = asyncio.new_event_loop()
        t = threading.Thread(target=lambda: loop.run_until_complete(_check()))
        t.start()
        event.wait(timeout=timeout + 1)
        loop.close()
        return result["ok"]

    # ------------------------------------------------------------------
    # Внутренняя реализация
    # ------------------------------------------------------------------

    def _run_event_loop(self):
        """Создать и запустить asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._send_queue = asyncio.Queue()
        try:
            self._loop.run_until_complete(self._maintain_connection())
        except Exception as e:
            logger.error(f"[hermes] Event loop завершился с ошибкой: {e}")
        finally:
            self._loop.close()

    async def _maintain_connection(self):
        """Поддерживать WebSocket-соединение с автореконнектом."""
        backoff = self.reconnect_interval_sec

        while self._running:
            try:
                logger.info(f"[hermes] Подключение к {self.url}...")
                async with websockets.connect(
                    self.url,
                    ping_interval=self.PING_INTERVAL,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    backoff = self.reconnect_interval_sec  # сброс backoff
                    logger.info("[hermes] Подключено")
                    if self.on_connect:
                        self.on_connect()

                    await self._session_loop(ws)

            except (ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                logger.warning(f"[hermes] Соединение разорвано: {e}")
            except Exception as e:
                logger.error(f"[hermes] Неожиданная ошибка: {e}")
            finally:
                self._connected = False
                self._ws = None
                if self.on_disconnect:
                    self.on_disconnect()

            if not self._running:
                break

            logger.info(f"[hermes] Переподключение через {backoff:.1f}с...")
            await asyncio.sleep(backoff)
            # Экспоненциальный backoff до MAX_RECONNECT_INTERVAL
            backoff = min(backoff * 2, self.MAX_RECONNECT_INTERVAL)

    async def _session_loop(self, ws: websockets.WebSocketClientProtocol):
        """
        Параллельная обработка: отправка из очереди и приём ответов.
        """
        send_task = asyncio.ensure_future(self._sender_loop(ws))
        recv_task = asyncio.ensure_future(self._receiver_loop(ws))

        done, pending = await asyncio.wait(
            [send_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _sender_loop(self, ws: websockets.WebSocketClientProtocol):
        """Отправлять аудио из очереди."""
        while self._running:
            try:
                wav_bytes = await asyncio.wait_for(
                    self._send_queue.get(), timeout=1.0
                )
                # Отправка как бинарный фрейм
                await ws.send(wav_bytes)
                logger.info(f"[hermes] Отправлено аудио: {len(wav_bytes)} байт")
            except asyncio.TimeoutError:
                continue
            except ConnectionClosed:
                raise
            except Exception as e:
                logger.error(f"[hermes] Ошибка отправки: {e}")

    async def _receiver_loop(self, ws: websockets.WebSocketClientProtocol):
        """Получать ответы от Hermes Agent."""
        async for message in ws:
            if not self._running:
                break
            try:
                # Принимаем байты (WAV) или base64-строку
                if isinstance(message, bytes):
                    audio_data = message
                elif isinstance(message, str):
                    # Попробовать декодировать как base64 WAV
                    try:
                        audio_data = base64.b64decode(message)
                    except Exception:
                        logger.warning(
                            f"[hermes] Получено текстовое сообщение: {message[:100]}"
                        )
                        continue
                else:
                    continue

                logger.info(
                    f"[hermes] Получен аудио-ответ: {len(audio_data)} байт"
                )
                if self.on_audio_response:
                    self.on_audio_response(audio_data)

            except Exception as e:
                logger.error(f"[hermes] Ошибка обработки ответа: {e}")
