# ytdlp_updater.py - Versión de yt-dlp y actualización con pip
"""
yt-dlp es el componente que entiende las páginas de video. Los sitios cambian a
menudo y una versión vieja deja de reconocerlos, así que Geas puede comprobar
la última versión publicada (PyPI) y actualizarla en su propio entorno de Python.
Después hay que reiniciar Geas: yt-dlp carga partes de sí mismo a medida que
las usa y no debe mezclar las de dos versiones.
"""
import importlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from importlib import metadata

PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"


def installed_version():
    """Versión instalada en el entorno de Geas (la del disco, aunque se acabe de actualizar)."""
    importlib.invalidate_caches()
    try:
        return metadata.version("yt-dlp")
    except metadata.PackageNotFoundError:
        return None


def latest_version(timeout=10):
    """Última versión publicada. Lanza una excepción si no hay conexión."""
    request = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json", "User-Agent": "Geas"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)["info"]["version"]


def version_key(version):
    """'2026.09.30' y '2026.9.30' -> (2026, 9, 30), para comparar versiones."""
    return tuple(int(part) for part in re.findall(r"\d+", version or ""))


def is_newer(candidate, current):
    return bool(candidate) and version_key(candidate) > version_key(current)


def python_for_pip():
    """python.exe del entorno de Geas (si Geas corre con pythonw.exe, pip no tendría salida)."""
    folder, name = os.path.split(sys.executable)
    if name.lower() == "pythonw.exe":
        console = os.path.join(folder, "python.exe")
        if os.path.exists(console):
            return console
    return sys.executable


def update_command():
    return [python_for_pip(), "-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
            "--no-input", "yt-dlp"]


def run_update(timeout=600):
    """Actualiza yt-dlp. Devuelve (correcto, salida de pip)."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(update_command(), capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return result.returncode == 0, (result.stdout + "\n" + result.stderr).strip()
