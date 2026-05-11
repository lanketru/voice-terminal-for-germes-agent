"""
main.py — VoiceTerm entry point. Selects mode: setup or working.
           Точка входа VoiceTerm. Выбирает режим: настройка или рабочий.
"""

import logging
import os
import sys
import asyncio
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("voiceterm")

import config as cfg
from audio_player import AudioPlayer
from audio_recorder import AudioRecorder
from hotword_listener import HotwordListener
from hermes_client import HermesClient
from bt_live_mode import LiveModeController


def run_setup_mode():
    """Start initial setup mode (WiFi AP + web interface). / Запустить режим первоначальной настройки (WiFi AP + веб-интерфейс)."""
    logger.info("=== Режим настройки ===")
    # Start Access Point (call script) / Поднять точку доступа (вызов скрипта)
    ap_script = os.path.join(os.path.dirname(__file__), "scripts", "setup_ap.sh")
    if os.path.exists(ap_script):
        os.system(f"bash {ap_script}")
    else:
        logger.warning("setup_ap.sh not found, AP not started / setup_ap.sh не найден, AP не поднята")

    from setup_server.app import run_setup_server
    run_setup_server(host="0.0.0.0", port=8080)


class VoiceTermApp:
    """Main working mode app. / Основное приложение рабочего режима."""

    def __init__(self, config: dict):
        self.config = config
        self._player = AudioPlayer(
            device_index=config.get("audio_device_index")
        )
        self._recorder = AudioRecorder(
            silence_threshold=config.get("silence_threshold_rms", 200),
            silence_duration_ms=config.get("silence_duration_ms", 1500),
            max_duration_sec=30,
            device_index=config.get("audio_device_index"),
        )
        self._hermes = HermesClient(
            url=config["hermes_url"],
            reconnect_interval_sec=config.get("reconnect_interval_sec", 1),
            on_audio_response=self._on_hermes_audio,
            on_connect=lambda: logger.info("Hermes: подключено"),
            on_disconnect=lambda: logger.info("Hermes: отключено"),
        )
        self._hotword = HotwordListener(
            reference_file=config["reference_file_path"],
            hotword=config["wakeword"],
            threshold=config.get("hotword_threshold", 0.8),
            relaxation_time=config.get("relaxation_time", 2.0),
            window_length_secs=config.get("window_length_secs", 1.5),
            sliding_window_secs=config.get("sliding_window_secs", 0.75),
            device_index=config.get("audio_device_index"),
            on_detection=self._on_wakeword,
        )
        self._live_ctrl = LiveModeController(
            config=config,
            ws_url=config["hermes_url"],
            on_live_start=self._on_live_start,
            on_live_stop=self._on_live_stop,
        )
        self._recording_lock = threading.Lock()

    def _on_live_start(self):
        """Live mode activated — pause hotword. / Live-режим активирован — приостановить hotword."""
        logger.info("Live-режим: hotword приостановлен")
        self._hotword.stop()

    def _on_live_stop(self):
        """Live mode finished — resume hotword. / Live-режим завершён — возобновить hotword."""
        logger.info("Live-режим завершён: hotword возобновлён")
        self._hotword.start()

    def _on_hermes_audio(self, wav_bytes: bytes):
        """Play audio response from Hermes. / Воспроизвести аудио-ответ от Hermes."""
        logger.info(f"Получен ответ: {len(wav_bytes)} байт")
        self._player.play_wav_bytes(wav_bytes, block=True)

    def _on_wakeword(self, confidence: float):
        """Handle wake word detection. / Обработка обнаружения ключевого слова."""
        if not self._recording_lock.acquire(blocking=False):
            logger.info("Recording already in progress, skipping / Запись уже идёт, пропускаю")
            return
        try:
            logger.info(f"Wake word! confidence={confidence:.3f}")
            # Beep-сигнал
            if self.config.get("beep_enabled", True):
                beep = self.config.get("beep_wav_path", "")
                if beep and os.path.exists(beep):
                    self._player.play_wav_file(beep, block=True)

            # Stop hotword listening during recording / Остановить hotword-прослушивание на время записи
            self._hotword.stop()

            # Записать команду
            logger.info("Запись команды...")
            wav_path = self._recorder.record_until_silence()

            # Send to Hermes / Отправить в Hermes
            with open(wav_path, "rb") as f:
                wav_bytes = f.read()
            self._hermes.send_audio(wav_bytes)

            # Delete temporary file / Удалить временный файл
            try:
                os.remove(wav_path)
            except OSError:
                pass

            # Resume listening / Возобновить прослушивание
            self._hotword.start()
        except Exception as e:
            logger.error(f"Ошибка обработки wake word: {e}")
            self._hotword.start()
        finally:
            self._recording_lock.release()

    def run(self):
        """Run the application. / Запустить приложение."""
        logger.info("=== Рабочий режим ===")
        logger.info(f"Wake word: {self.config['wakeword']}")
        logger.info(f"Hermes URL: {self.config['hermes_url']}")

        # Connect to Bluetooth if configured / Подключиться к Bluetooth если настроен
        if self.config.get("audio_channel") == "bluetooth":
            mac = self.config.get("bluetooth_mac", "")
            if mac:
                from bluetooth_manager import BluetoothManager
                bt = BluetoothManager()
                logger.info(f"Подключение к BT: {mac}")
                bt.connect_device(mac)
                bt.set_as_audio_sink(mac)

        # Start Hermes client / Запустить Hermes-клиент
        self._hermes.start()

        # Start wake word listening / Запустить прослушивание ключевого слова
        self._hotword.start()

        # Start monitoring BT headset button (Live mode) / Запустить мониторинг кнопки BT-гарнитуры (Live-режим)
        self._live_ctrl.setup()

        logger.info("System started. Waiting for wake word... / Система запущена. Ожидание ключевого слова...")
        try:
            # Keep main thread alive / Держать главный поток живым
            while True:
                threading.Event().wait(60)
        except KeyboardInterrupt:
            logger.info("Stopping... / Остановка...")
        finally:
            self._hotword.stop()
            self._hermes.stop()
            self._live_ctrl.shutdown()


def main():
    config = cfg.load_config()
    if not cfg.is_setup_complete():
        run_setup_mode()
    else:
        app = VoiceTermApp(config)
        app.run()


if __name__ == "__main__":
    main()
