"""
setup_server/app.py — Flask web server for VoiceTerm setup.
Serves the configuration web interface and REST API endpoints.
"""

import sys
import os
import json
import logging
import tempfile
import queue
import threading
from pathlib import Path

# Add project root to sys.path / Добавляем корень проекта в sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS

import config as cfg
from setup_server import wifi_manager
from audio_player import list_output_devices, list_input_devices, AudioPlayer
from audio_recorder import AudioRecorder
from bluetooth_manager import BluetoothManager
from hotword_listener import generate_wakeword_reference, test_hotword_realtime
from hermes_client import HermesClient

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates",
            static_folder="static", static_url_path="/static")
CORS(app)

# Server state / Состояние сервера
_bt_manager = BluetoothManager()
_wakeword_samples: list = []  # Список путей к WAV-образцам
_sse_queues: list = []  # SSE клиенты для bluetooth-scan
_confidence_queue: queue.Queue = queue.Queue()

# ------------------------------------------------------------------
# Утилиты
# ------------------------------------------------------------------

def _sse_event(data: dict) -> str:
    """Форматировать SSE-событие."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ------------------------------------------------------------------
# Маршруты — страница
# ------------------------------------------------------------------

@app.route("/")
def index():
    """Главная страница настроек."""
    return render_template("index.html")


# ------------------------------------------------------------------
# WiFi
# ------------------------------------------------------------------

@app.route("/api/wifi/scan", methods=["GET"])
def wifi_scan():
    """Сканировать WiFi-сети."""
    networks = wifi_manager.scan_networks()
    return jsonify({"networks": networks})


@app.route("/api/wifi/connect", methods=["POST"])
def wifi_connect():
    """Подключиться к WiFi-сети."""
    data = request.get_json(force=True)
    ssid = data.get("ssid", "").strip()
    password = data.get("password", "").strip()
    if not ssid:
        return jsonify({"status": "error", "message": "SSID не указан"}), 400
    result = wifi_manager.connect_to_network(ssid, password)
    return jsonify(result)


@app.route("/api/wifi/status", methods=["GET"])
def wifi_status():
    """Текущее состояние WiFi."""
    status = wifi_manager.get_current_connection()
    return jsonify(status)


# ------------------------------------------------------------------
# Аудио устройства
# ------------------------------------------------------------------

@app.route("/api/audio/devices", methods=["GET"])
def audio_devices():
    """Получить список аудиоустройств ввода и вывода."""
    return jsonify({
        "output": list_output_devices(),
        "input": list_input_devices(),
    })


@app.route("/api/audio/test_playback", methods=["POST"])
def audio_test_playback():
    """Воспроизвести тестовый WAV-файл."""
    data = request.get_json(force=True)
    device_index = data.get("device_index")  # может быть None

    config = cfg.load_config()
    beep_path = config.get("beep_wav_path", "")

    # Если beep-файл отсутствует, использовать встроенный генератор
    test_wav = beep_path if beep_path and os.path.exists(beep_path) else _generate_test_tone()

    player = AudioPlayer(device_index=device_index)
    ok = player.play_wav_file(test_wav, block=False)
    return jsonify({"status": "ok" if ok else "error"})


@app.route("/api/audio/test_mic", methods=["POST"])
def audio_test_mic():
    """Записать 3 секунды с микрофона и воспроизвести обратно."""
    data = request.get_json(force=True)
    device_index = data.get("device_index")

    config = cfg.load_config()
    recorder = AudioRecorder(device_index=device_index)
    try:
        wav_path = recorder.record_fixed_duration(3.0)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    player = AudioPlayer(device_index=device_index)
    player.play_wav_file(wav_path, block=False)
    return jsonify({"status": "ok", "file": wav_path})


def _generate_test_tone() -> str:
    """Сгенерировать простой тестовый WAV-тон (440 Гц, 1 сек)."""
    import wave
    import struct
    import math

    fd, path = tempfile.mkstemp(suffix=".wav", prefix="voiceterm_test_")
    os.close(fd)
    sample_rate = 16000
    duration = 1.0
    frequency = 440.0
    num_samples = int(sample_rate * duration)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(num_samples):
            sample = int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
            wf.writeframes(struct.pack("<h", sample))
    return path


# ------------------------------------------------------------------
# Bluetooth
# ------------------------------------------------------------------

@app.route("/api/bluetooth/scan/start", methods=["POST"])
def bt_scan_start():
    """Начать сканирование Bluetooth устройств."""
    def on_device(mac, name):
        event = _sse_event({"mac": mac, "name": name})
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)

    _bt_manager.start_scan(on_device_found=on_device, duration_sec=30)
    return jsonify({"status": "scanning"})


@app.route("/api/bluetooth/scan/devices", methods=["GET"])
def bt_scan_devices():
    """SSE-поток обнаруженных Bluetooth устройств."""
    q: queue.Queue = queue.Queue(maxsize=50)
    _sse_queues.append(q)

    # Отправить уже найденные устройства
    for dev in _bt_manager.get_found_devices():
        q.put_nowait(_sse_event(dev))

    def generate():
        try:
            while True:
                try:
                    data = q.get(timeout=30)
                    yield data
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            if q in _sse_queues:
                _sse_queues.remove(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/bluetooth/pair", methods=["POST"])
def bt_pair():
    """Сопрячь Bluetooth-устройство (pair + trust + connect)."""
    data = request.get_json(force=True)
    mac = data.get("mac", "").strip()
    if not mac:
        return jsonify({"status": "error", "message": "MAC не указан"}), 400

    result = _bt_manager.pair_trust_connect(mac)
    all_ok = all(result.values())
    return jsonify({
        "status": "ok" if all_ok else "error",
        "details": result,
    })


@app.route("/api/bluetooth/status", methods=["GET"])
def bt_status():
    """Проверить статус подключения Bluetooth."""
    mac = request.args.get("mac", "")
    if not mac:
        return jsonify({"connected": False})
    connected = _bt_manager.get_connection_status(mac)
    return jsonify({"connected": connected})


# ------------------------------------------------------------------
# Обучение ключевому слову
# ------------------------------------------------------------------

@app.route("/api/wakeword/record_sample", methods=["POST"])
def wakeword_record_sample():
    """Записать образец ключевого слова (2 секунды)."""
    data = request.get_json(force=True)
    device_index = data.get("device_index")

    recorder = AudioRecorder(device_index=device_index)
    try:
        wakewords_dir = cfg.WAKEWORDS_DIR / "samples"
        wakewords_dir.mkdir(parents=True, exist_ok=True)
        sample_num = len(_wakeword_samples) + 1
        out_path = str(wakewords_dir / f"sample_{sample_num}.wav")
        wav_path = recorder.record_fixed_duration(2.0, output_path=out_path)
        _wakeword_samples.append(wav_path)
        return jsonify({
            "status": "ok",
            "sample_number": sample_num,
            "total_samples": len(_wakeword_samples),
            "file": wav_path,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/wakeword/clear_samples", methods=["POST"])
def wakeword_clear_samples():
    """Очистить накопленные образцы."""
    _wakeword_samples.clear()
    return jsonify({"status": "ok"})


@app.route("/api/wakeword/generate", methods=["POST"])
def wakeword_generate():
    """Сгенерировать reference-файл по накопленным образцам."""
    data = request.get_json(force=True)
    hotword = data.get("hotword", "").strip()
    if not hotword:
        return jsonify({"status": "error", "message": "hotword не указан"}), 400
    if len(_wakeword_samples) < 4:
        return jsonify({
            "status": "error",
            "message": f"Нужно минимум 4 образца, есть {len(_wakeword_samples)}",
        }), 400

    try:
        ref_path = generate_wakeword_reference(
            hotword=hotword,
            wav_files=_wakeword_samples,
            output_dir=str(cfg.WAKEWORDS_DIR),
        )
        return jsonify({"status": "ok", "reference_file": ref_path})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/wakeword/test", methods=["GET"])
def wakeword_test():
    """SSE-поток confidence при тестировании ключевого слова (10 секунд)."""
    data = request.args
    reference_file = data.get("reference_file", "")
    hotword = data.get("hotword", "")
    threshold = float(data.get("threshold", 0.8))

    if not reference_file or not hotword:
        return jsonify({"status": "error", "message": "Параметры не указаны"}), 400

    conf_q: queue.Queue = queue.Queue()

    def run_test():
        try:
            test_hotword_realtime(
                reference_file=reference_file,
                hotword=hotword,
                threshold=threshold,
                duration_sec=10,
                confidence_callback=lambda c: conf_q.put_nowait(c),
            )
        except Exception as e:
            conf_q.put_nowait({"error": str(e)})
        finally:
            conf_q.put_nowait(None)  # Сигнал завершения

    t = threading.Thread(target=run_test, daemon=True)
    t.start()

    def generate():
        while True:
            val = conf_q.get(timeout=15)
            if val is None:
                yield _sse_event({"done": True})
                break
            if isinstance(val, dict):
                yield _sse_event(val)
            else:
                yield _sse_event({"confidence": val})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ------------------------------------------------------------------
# Hermes Agent
# ------------------------------------------------------------------

@app.route("/api/hermes/check", methods=["POST"])
def hermes_check():
    """Проверить WebSocket-соединение с Hermes Agent."""
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"status": "error", "message": "URL не указан"}), 400

    client = HermesClient(url=url)
    ok = client.check_connection(timeout=5.0)
    return jsonify({
        "status": "ok" if ok else "error",
        "message": "Соединение успешно" if ok else "Не удалось подключиться",
    })


# ------------------------------------------------------------------
# Конфигурация
# ------------------------------------------------------------------

@app.route("/api/config", methods=["GET"])
def get_config():
    """Получить текущую конфигурацию."""
    config = cfg.load_config()
    return jsonify(config)


@app.route("/api/config/save", methods=["POST"])
def save_config():
    """Сохранить конфигурацию и завершить настройку."""
    data = request.get_json(force=True)
    config = cfg.load_config()
    config.update(data)
    config["setup_complete"] = True

    if cfg.save_config(config):
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "message": "Ошибка сохранения"}), 500


# ------------------------------------------------------------------
# Запуск
# ------------------------------------------------------------------

def run_setup_server(host: str = "0.0.0.0", port: int = 8080, debug: bool = False):
    """Запустить Flask-сервер настроек."""
    logger.info(f"[setup] Запуск сервера на {host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    run_setup_server(debug=True)
