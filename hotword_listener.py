"""
hotword_listener.py — Интеграция EfficientWord-Net для обнаружения ключевого слова
"""

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class HotwordListener:
    def __init__(self, reference_file: str, hotword: str, threshold: float = 0.8,
                 relaxation_time: float = 2.0, window_length_secs: float = 1.5,
                 sliding_window_secs: float = 0.75, device_index: Optional[int] = None,
                 on_detection: Optional[Callable[[float], None]] = None):
        self.reference_file = reference_file
        self.hotword = hotword
        self.threshold = threshold
        self.relaxation_time = relaxation_time
        self.window_length_secs = max(window_length_secs, 1.5)
        self.sliding_window_secs = sliding_window_secs
        self.device_index = device_index
        self.on_detection = on_detection
        self._running = False
        self._thread = None
        self._base_model = None
        self._detector = None
        self._mic_stream = None

    def _load_model(self):
        from eff_word_net.audio_processing import Resnet50_Arc_loss
        from eff_word_net.engine import HotwordDetector
        from eff_word_net.streams import SimpleMicStream
        logger.info("[hotword] Загрузка модели Resnet50_Arc_loss (~88MB)...")
        self._base_model = Resnet50_Arc_loss()
        logger.info("[hotword] Модель загружена")
        self._detector = HotwordDetector(
            hotword=self.hotword, model=self._base_model,
            reference_file=self.reference_file, threshold=self.threshold,
            relaxation_time=self.relaxation_time)
        stream_kwargs = {"window_length_secs": self.window_length_secs,
                         "sliding_window_secs": self.sliding_window_secs}
        if self.device_index is not None:
            stream_kwargs["device_index"] = self.device_index
        self._mic_stream = SimpleMicStream(**stream_kwargs)

    def _listen_loop(self):
        self._mic_stream.start_stream()
        logger.info(f"[hotword] Прослушивание ключевого слова: '{self.hotword}'")
        try:
            while self._running:
                frame = self._mic_stream.getFrame()
                result = self._detector.scoreFrame(frame)
                if result is None:
                    continue
                if result["match"]:
                    confidence = result.get("confidence", 0.0)
                    logger.info(f"[hotword] Обнаружено! Confidence: {confidence:.3f}")
                    if self.on_detection:
                        try:
                            self.on_detection(confidence)
                        except Exception as e:
                            logger.error(f"[hotword] Ошибка в callback: {e}")
        except Exception as e:
            if self._running:
                logger.error(f"[hotword] Ошибка в цикле: {e}")
        finally:
            try:
                self._mic_stream.stop_stream()
            except Exception:
                pass

    def start(self):
        if self._running:
            return
        if self._base_model is None:
            self._load_model()
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="HotwordListener")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("[hotword] Прослушивание остановлено")

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()


def generate_wakeword_reference(hotword: str, wav_files: list, output_dir: str) -> str:
    if len(wav_files) < 4:
        raise ValueError(f"Нужно минимум 4 образца WAV, передано: {len(wav_files)}")
    output_path = str(Path(output_dir) / f"{hotword}_ref.json")
    try:
        from eff_word_net import generate_reference
        generate_reference.generate(hotword=hotword, wav_files=wav_files, output_dir=output_dir)
        logger.info(f"[hotword] Reference файл создан: {output_path}")
        return output_path
    except Exception as e:
        raise RuntimeError(f"Ошибка генерации reference: {e}") from e


def test_hotword_realtime(reference_file: str, hotword: str, threshold: float = 0.8,
                          duration_sec: int = 10,
                          confidence_callback: Optional[Callable[[float], None]] = None):
    import time
    from eff_word_net.audio_processing import Resnet50_Arc_loss
    from eff_word_net.engine import HotwordDetector
    from eff_word_net.streams import SimpleMicStream
    base_model = Resnet50_Arc_loss()
    detector = HotwordDetector(hotword=hotword, model=base_model,
                                reference_file=reference_file, threshold=threshold,
                                relaxation_time=0.5)
    mic_stream = SimpleMicStream(window_length_secs=1.5, sliding_window_secs=0.75)
    mic_stream.start_stream()
    start = time.time()
    try:
        while time.time() - start < duration_sec:
            frame = mic_stream.getFrame()
            result = detector.scoreFrame(frame)
            if result is not None and confidence_callback:
                confidence_callback(result.get("confidence", 0.0))
    finally:
        mic_stream.stop_stream()
