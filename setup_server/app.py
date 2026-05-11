"""
setup_server/app.py — Flask веб-сервер для настройки VoiceTerm
"""

import sys
import os
import json
import logging
import tempfile
import queue
import threading
from pathlib import Path

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

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")
CORS(app)

_bt_manager = BluetoothManager()
_wakeword_samples: list = []
_sse_queues: list = []


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/wifi/scan")
def wifi_scan():
    return jsonify({"networks": wifi_manager.scan_networks()})


@app.route("/api/wifi/connect", methods=["POST"])
def wifi_connect():
    data = request.get_json(force=True)
    ssid = data.get("ssid", "").strip()
    if not ssid:
        return jsonify({"status": "error", "message": "SSID не указан"}), 400
    return jsonify(wifi_manager.connect_to_network(ssid, data.get("password", "").strip()))


@app.route("/api/wifi/status")
def wifi_status():
    return jsonify(wifi_manager.get_current_connection())


@app.route("/api/audio/devices")
def audio_devices():
    return jsonify({"output": list_output_devices(), "input": list_input_devices()})


@app.route("/api/audio/test_playback", methods=["POST"])
def audio_test_playback():
    data = request.get_json(force=True)
    device_index = data.get("device_index")
    config = cfg.load_config()
    beep_path = config.get("beep_wav_path", "")
    test_wav = beep_path if beep_path and os.path.exists(beep_path) else _generate_test_tone()
    player = AudioPlayer(device_index=device_index)
    ok = player.play_wav_file(test_wav, block=False)
    return jsonify({"status": "ok" if ok else "error"})


@app.route("/api/audio/test_mic", methods=["POST"])
def audio_test_mic():
    data = request.get_json(force=True)
    device_index = data.get("device_index")
    recorder = AudioRecorder(device_index=device_index)
    try:
        wav_path = recorder.record_fixed_duration(3.0)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    AudioPlayer(device_index=device_index).play_wav_file(wav_path, block=False)
    return jsonify({"status": "ok", "file": wav_path})


def _generate_test_tone() -> str:
    import wave, struct, math
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="voiceterm_test_")
    os.close(fd)
    sr, dur, freq = 16000, 1.0, 440.0
    n = int(sr * dur)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        for i in range(n):
            wf.writeframes(struct.pack("<h", int(32767 * math.sin(2 * math.pi * freq * i / sr))))
    return path


@app.route("/api/bluetooth/scan/start", methods=["POST"])
def bt_scan_start():
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


@app.route("/api/bluetooth/scan/devices")
def bt_scan_devices():
    q: queue.Queue = queue.Queue(maxsize=50)
    _sse_queues.append(q)
    for dev in _bt_manager.get_found_devices():
        q.put_nowait(_sse_event(dev))

    def generate():
        try:
            while True:
                try:
                    yield q.get(timeout=30)
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            if q in _sse_queues:
                _sse_queues.remove(q)

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/bluetooth/pair", methods=["POST"])
def bt_pair():
    data = request.get_json(force=True)
    mac = data.get("mac", "").strip()
    if not mac:
        return jsonify({"status": "error", "message": "MAC не указан"}), 400
    result = _bt_manager.pair_trust_connect(mac)
    return jsonify({"status": "ok" if all(result.values()) else "error", "details": result})


@app.route("/api/bluetooth/status")
def bt_status():
    mac = request.args.get("mac", "")
    if not mac:
        return jsonify({"connected": False})
    return jsonify({"connected": _bt_manager.get_connection_status(mac)})


@app.route("/api/wakeword/record_sample", methods=["POST"])
def wakeword_record_sample():
    data = request.get_json(force=True)
    recorder = AudioRecorder(device_index=data.get("device_index"))
    try:
        wakewords_dir = cfg.WAKEWORDS_DIR / "samples"
        wakewords_dir.mkdir(parents=True, exist_ok=True)
        sample_num = len(_wakeword_samples) + 1
        out_path = str(wakewords_dir / f"sample_{sample_num}.wav")
        wav_path = recorder.record_fixed_duration(2.0, output_path=out_path)
        _wakeword_samples.append(wav_path)
        return jsonify({"status": "ok", "sample_number": sample_num,
                        "total_samples": len(_wakeword_samples), "file": wav_path})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/wakeword/clear_samples", methods=["POST"])
def wakeword_clear_samples():
    _wakeword_samples.clear()
    return jsonify({"status": "ok"})


@app.route("/api/wakeword/generate", methods=["POST"])
def wakeword_generate():
    data = request.get_json(force=True)
    hotword = data.get("hotword", "").strip()
    if not hotword:
        return jsonify({"status": "error", "message": "hotword не указан"}), 400
    if len(_wakeword_samples) < 4:
        return jsonify({"status": "error",
                        "message": f"Нужно минимум 4 образца, есть {len(_wakeword_samples)}"}), 400
    try:
        ref_path = generate_wakeword_reference(
            hotword=hotword, wav_files=_wakeword_samples, output_dir=str(cfg.WAKEWORDS_DIR))
        return jsonify({"status": "ok", "reference_file": ref_path})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/wakeword/test")
def wakeword_test():
    reference_file = request.args.get("reference_file", "")
    hotword = request.args.get("hotword", "")
    threshold = float(request.args.get("threshold", 0.8))
    if not reference_file or not hotword:
        return jsonify({"status": "error", "message": "Параметры не указаны"}), 400
    conf_q: queue.Queue = queue.Queue()

    def run_test():
        try:
            test_hotword_realtime(reference_file=reference_file, hotword=hotword,
                                   threshold=threshold, duration_sec=10,
                                   confidence_callback=lambda c: conf_q.put_nowait(c))
        except Exception as e:
            conf_q.put_nowait({"error": str(e)})
        finally:
            conf_q.put_nowait(None)

    threading.Thread(target=run_test, daemon=True).start()

    def generate():
        while True:
            val = conf_q.get(timeout=15)
            if val is None:
                yield _sse_event({"done": True})
                break
            yield _sse_event(val if isinstance(val, dict) else {"confidence": val})

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache"})


@app.route("/api/hermes/check", methods=["POST"])
def hermes_check():
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"status": "error", "message": "URL не указан"}), 400
    ok = HermesClient(url=url).check_connection(timeout=5.0)
    return jsonify({"status": "ok" if ok else "error",
                    "message": "Соединение успешно" if ok else "Не удалось подключиться"})


@app.route("/api/config")
def get_config():
    return jsonify(cfg.load_config())


@app.route("/api/config/save", methods=["POST"])
def save_config():
    data = request.get_json(force=True)
    config = cfg.load_config()
    config.update(data)
    config["setup_complete"] = True
    if cfg.save_config(config):
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "message": "Ошибка сохранения"}), 500


def run_setup_server(host: str = "0.0.0.0", port: int = 8080, debug: bool = False):
    logger.info(f"[setup] Запуск сервера на {host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    run_setup_server(debug=True)
