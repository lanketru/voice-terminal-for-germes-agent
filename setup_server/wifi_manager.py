"""
setup_server/wifi_manager.py — Управление WiFi через nmcli
"""

import subprocess
import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


def _run(cmd: List[str], timeout: int = 15) -> tuple:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        logger.warning(f"[wifi] Таймаут: {' '.join(cmd)}")
        return "", -1
    except FileNotFoundError:
        logger.error(f"[wifi] Команда не найдена: {cmd[0]}")
        return "", -1


def scan_networks() -> List[Dict]:
    _run(["nmcli", "device", "wifi", "rescan"])
    out, code = _run(["nmcli", "--terse", "--fields", "SSID,SIGNAL,SECURITY",
                      "device", "wifi", "list"])
    networks = []
    if code != 0:
        return networks
    seen_ssids = set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        ssid = parts[0].strip()
        if not ssid or ssid in seen_ssids:
            continue
        seen_ssids.add(ssid)
        try:
            signal = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            signal = 0
        security = parts[2].strip() if len(parts) > 2 else ""
        networks.append({"ssid": ssid, "signal": signal, "security": security})
    networks.sort(key=lambda x: x["signal"], reverse=True)
    return networks


def connect_to_network(ssid: str, password: str) -> Dict[str, str]:
    if password:
        cmd = ["nmcli", "device", "wifi", "connect", ssid, "password", password]
    else:
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
    out, code = _run(cmd, timeout=30)
    if code == 0 and ("successfully" in out.lower() or "активировано" in out.lower()):
        logger.info(f"[wifi] Подключено к {ssid}")
        return {"status": "ok", "message": f"Успешно подключено к {ssid}"}
    return {"status": "error", "message": out or "Не удалось подключиться"}


def get_current_connection() -> Dict:
    out, code = _run(["nmcli", "-t", "-f", "ACTIVE,SSID,IP4.ADDRESS", "device", "wifi"])
    for line in out.splitlines():
        if line.startswith("yes:"):
            parts = line.split(":")
            ssid = parts[1] if len(parts) > 1 else ""
            return {"connected": True, "ssid": ssid, "ip": ""}
    ip_out, _ = _run(["hostname", "-I"])
    ip = ip_out.split()[0] if ip_out else ""
    return {"connected": False, "ssid": "", "ip": ip}
