"""
bluetooth_manager.py — Bluetooth management via bluetoothctl.
                        Управление Bluetooth через bluetoothctl.
"""

import subprocess
import re
import logging
import threading
import time
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _run(cmd: List[str], timeout: int = 10) -> tuple:
    """
    Выполнить команду и вернуть (stdout, returncode).

    Args:
        cmd: Список аргументов команды.
        timeout: Таймаут в секундах.

    Returns:
        Кортеж (stdout: str, returncode: int).
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        logger.warning(f"[bt] Таймаут команды: {' '.join(cmd)}")
        return "", -1
    except FileNotFoundError:
        logger.error(f"[bt] Команда не найдена: {cmd[0]}")
        return "", -1


class BluetoothManager:
    """Управление Bluetooth устройствами через bluetoothctl."""

    def __init__(self):
        self._scan_process: Optional[subprocess.Popen] = None
        self._scan_thread: Optional[threading.Thread] = None
        self._scanning = False
        self._found_devices: Dict[str, str] = {}  # MAC -> Name
        self._scan_callback = None

    # ------------------------------------------------------------------
    # Поиск устройств
    # ------------------------------------------------------------------

    def start_scan(self, on_device_found=None, duration_sec: int = 30):
        """
        Начать сканирование Bluetooth устройств.

        Args:
            on_device_found: Callback(mac: str, name: str) при обнаружении устройства.
            duration_sec: Длительность сканирования в секундах.
        """
        if self._scanning:
            logger.warning("[bt] Сканирование уже запущено")
            return

        self._scanning = True
        self._found_devices = {}
        self._scan_callback = on_device_found

        self._scan_thread = threading.Thread(
            target=self._scan_worker,
            args=(duration_sec,),
            daemon=True,
            name="BTScan",
        )
        self._scan_thread.start()

    def _scan_worker(self, duration_sec: int):
        """Поток сканирования: парсит вывод bluetoothctl."""
        try:
            self._scan_process = subprocess.Popen(
                ["bluetoothctl"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            # Включить сканирование
            self._scan_process.stdin.write("scan on\n")
            self._scan_process.stdin.flush()

            end_time = time.time() + duration_sec
            pattern = re.compile(
                r"\[NEW\] Device ([0-9A-F:]{17}) (.+)"
            )

            while time.time() < end_time and self._scanning:
                line = self._scan_process.stdout.readline()
                if not line:
                    break
                m = pattern.search(line)
                if m:
                    mac = m.group(1)
                    name = m.group(2).strip()
                    if mac not in self._found_devices:
                        self._found_devices[mac] = name
                        logger.info(f"[bt] Найдено: {name} ({mac})")
                        if self._scan_callback:
                            self._scan_callback(mac, name)

        except Exception as e:
            logger.error(f"[bt] Ошибка сканирования: {e}")
        finally:
            self.stop_scan()

    def stop_scan(self):
        """Остановить сканирование."""
        self._scanning = False
        if self._scan_process:
            try:
                self._scan_process.stdin.write("scan off\nquit\n")
                self._scan_process.stdin.flush()
                self._scan_process.wait(timeout=3)
            except Exception:
                try:
                    self._scan_process.kill()
                except Exception:
                    pass
            self._scan_process = None

    def get_found_devices(self) -> List[Dict[str, str]]:
        """
        Получить список найденных устройств.

        Returns:
            Список словарей с ключами: mac, name.
        """
        return [{"mac": mac, "name": name} for mac, name in self._found_devices.items()]

    # ------------------------------------------------------------------
    # Сопряжение, доверие и подключение
    # ------------------------------------------------------------------

    def pair_device(self, mac: str) -> bool:
        """
        Сопрячь Bluetooth-устройство.

        Args:
            mac: MAC-адрес устройства.

        Returns:
            True при успехе.
        """
        out, code = _run(["bluetoothctl", "pair", mac])
        success = code == 0 or "successful" in out.lower()
        logger.info(f"[bt] pair {mac}: {'OK' if success else 'FAIL'} - {out}")
        return success

    def trust_device(self, mac: str) -> bool:
        """
        Добавить устройство в доверенные.

        Args:
            mac: MAC-адрес устройства.

        Returns:
            True при успехе.
        """
        out, code = _run(["bluetoothctl", "trust", mac])
        success = code == 0 or "trust succeeded" in out.lower()
        logger.info(f"[bt] trust {mac}: {'OK' if success else 'FAIL'}")
        return success

    def connect_device(self, mac: str) -> bool:
        """
        Подключиться к Bluetooth-устройству.

        Args:
            mac: MAC-адрес устройства.

        Returns:
            True при успехе.
        """
        out, code = _run(["bluetoothctl", "connect", mac], timeout=15)
        success = code == 0 or "connection successful" in out.lower()
        logger.info(f"[bt] connect {mac}: {'OK' if success else 'FAIL'} - {out}")
        return success

    def pair_trust_connect(self, mac: str) -> Dict[str, bool]:
        """
        Полный цикл: pair → trust → connect.

        Args:
            mac: MAC-адрес устройства.

        Returns:
            Словарь с результатами каждого шага.
        """
        paired = self.pair_device(mac)
        trusted = self.trust_device(mac)
        connected = self.connect_device(mac)
        return {
            "paired": paired,
            "trusted": trusted,
            "connected": connected,
        }

    def get_connection_status(self, mac: str) -> bool:
        """
        Проверить, подключено ли устройство.

        Args:
            mac: MAC-адрес устройства.

        Returns:
            True если устройство подключено.
        """
        out, _ = _run(["bluetoothctl", "info", mac])
        return "connected: yes" in out.lower()

    def set_as_audio_sink(self, mac: str) -> bool:
        """
        Задать Bluetooth-устройство как аудиовыход через pactl/PulseAudio.

        Args:
            mac: MAC-адрес устройства.

        Returns:
            True при успехе.
        """
        # Получить имя sink из pactl
        out, code = _run(["pactl", "list", "short", "sinks"])
        if code != 0:
            logger.error("[bt] pactl недоступен")
            return False

        # Нормализованный MAC для поиска в имени sink
        mac_norm = mac.replace(":", "_")
        sink_name = None
        for line in out.splitlines():
            if mac_norm.lower() in line.lower() or "bluez" in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    sink_name = parts[1]
                    break

        if not sink_name:
            logger.warning(f"[bt] Sink для {mac} не найден в pactl")
            return False

        _, code = _run(["pactl", "set-default-sink", sink_name])
        if code == 0:
            logger.info(f"[bt] Аудиовыход установлен: {sink_name}")
            return True
        logger.error(f"[bt] Не удалось установить sink: {sink_name}")
        return False
