#!/usr/bin/env python3
"""
Host de Native Messaging de Geas.

La extensión del navegador envía mensajes JSON por stdin (protocolo de Chrome:
4 bytes de longitud + JSON). El host los reenvía a la API local de Geas y,
si la aplicación no está abierta, la inicia y espera a que su API responda.

Acciones:
    {"action": "ping"}                       -> informa si Geas está abierta (no la inicia)
    {"action": "launch"}                     -> inicia Geas si está cerrada
    {"action": "download", "url": ..., ...}  -> envía una descarga (acción por defecto)
"""

import json
import logging
import struct
import subprocess
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
API_BASE = "http://127.0.0.1:5000"
STARTUP_TIMEOUT = 30  # segundos de espera a que Geas levante su API
LAUNCH_LOCK = Path(tempfile.gettempdir()) / "geas_launch.lock"
MAX_MESSAGE_SIZE = 64 * 1024 * 1024  # límite del protocolo de Chrome hacia el host

# Configurar logging para debugging (sin cookies ni cabeceras: pueden contener sesiones)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[RotatingFileHandler(SCRIPT_DIR / "native_host.log", maxBytes=1_000_000,
                                  backupCount=1, encoding="utf-8")]
)

# La API es local: no pasar por proxies configurados en el sistema
session = requests.Session()
session.trust_env = False


def get_message():
    """
    Lee un mensaje desde stdin siguiendo el protocolo de Native Messaging.

    Returns:
        dict: Mensaje parseado como JSON, o None si no hay más mensajes
    """
    try:
        raw_length = sys.stdin.buffer.read(4)
        if len(raw_length) < 4:
            return None

        message_length = struct.unpack('@I', raw_length)[0]
        if message_length > MAX_MESSAGE_SIZE:
            raise ValueError(f"Mensaje demasiado grande: {message_length} bytes")

        message = sys.stdin.buffer.read(message_length).decode('utf-8')
        return json.loads(message)
    except (struct.error, ValueError, UnicodeDecodeError) as e:
        logging.error(f"Error al leer mensaje: {e}")
        return None


def send_message(message):
    """
    Envía un mensaje a stdout siguiendo el protocolo de Native Messaging.

    Args:
        message (dict): Mensaje a enviar
    """
    try:
        content = json.dumps(message).encode('utf-8')
        sys.stdout.buffer.write(struct.pack('@I', len(content)))
        sys.stdout.buffer.write(content)
        sys.stdout.buffer.flush()
    except (TypeError, ValueError, OSError) as e:
        logging.error(f"Error al enviar mensaje: {e}")


def app_is_running():
    """True si la API de Geas responde."""
    try:
        return session.get(f"{API_BASE}/check", timeout=1.5).status_code == 200
    except requests.RequestException:
        return False


def launch_app():
    """Inicia Geas sin consola y separada del navegador."""
    main_script = SCRIPT_DIR / "main.py"
    if not main_script.exists():
        raise RuntimeError(f"main.py no encontrado en {SCRIPT_DIR}")

    # Si llegan varias descargas a la vez, solo la primera abre la aplicación
    if LAUNCH_LOCK.exists() and time.time() - LAUNCH_LOCK.stat().st_mtime < STARTUP_TIMEOUT:
        logging.info("Geas ya se está iniciando")
        return
    LAUNCH_LOCK.touch()

    python = Path(sys.executable)
    # Sin heredar los pipes del navegador: Geas sigue viva cuando el host termina
    options = dict(cwd=str(SCRIPT_DIR), stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)

    if sys.platform == 'win32':
        pythonw = python.with_name("pythonw.exe")
        if pythonw.exists():
            python = pythonw
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            # Fuera del "job" del navegador para que no se cierre junto con él
            subprocess.Popen([str(python), str(main_script)],
                             creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **options)
        except OSError:
            subprocess.Popen([str(python), str(main_script)], creationflags=flags, **options)
    else:
        subprocess.Popen([str(python), str(main_script)], start_new_session=True, **options)


def ensure_app_running():
    """Inicia Geas si hace falta y espera a su API. Devuelve True si responde."""
    if app_is_running():
        return True

    logging.info("Aplicación no está corriendo, iniciándola...")
    launch_app()
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        time.sleep(0.5)
        if app_is_running():
            LAUNCH_LOCK.unlink(missing_ok=True)  # ya arrancó: la próxima vez se puede volver a abrir
            return True
    return False


def forward_download(message):
    """Entrega la descarga a la API de Geas."""
    response = session.post(f"{API_BASE}/download", json=message, timeout=10)
    if response.status_code == 200:
        return {"status": "success", "text": "Descarga enviada a Geas"}
    try:
        error = response.json().get("error")
    except ValueError:
        error = None
    return {"status": "error", "text": error or f"Geas respondió HTTP {response.status_code}"}


def handle_message(message):
    if not isinstance(message, dict):
        return {"status": "error", "text": "Invalid message format"}

    action = message.get("action", "download")
    if action == "ping":
        return {"status": "success", "app_running": app_is_running()}

    if action == "launch":
        if ensure_app_running():
            return {"status": "success", "text": "Geas está en ejecución"}
        return {"status": "error", "text": f"Geas no respondió después de {STARTUP_TIMEOUT} segundos"}

    if action != "download" or not isinstance(message.get("url"), str):
        return {"status": "error", "text": "Invalid message format"}

    logging.info("Descarga (%s): %s [%d cookies]", message.get("kind"),
                 message["url"][:200], len(message.get("cookies") or []))
    if not ensure_app_running():
        return {"status": "error", "text": f"Geas no respondió después de {STARTUP_TIMEOUT} segundos"}
    return forward_download(message)


def main():
    """
    Función principal que maneja la comunicación entre la extensión y la aplicación.
    """
    while True:
        message = get_message()
        if message is None:
            break
        try:
            send_message(handle_message(message))
        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.error(f"Error inesperado: {e}")
            send_message({"status": "error", "text": f"Error interno: {e}"})


if __name__ == '__main__':
    main()
