# ytdlp_updater.py - Versión de yt-dlp y su actualización
"""
yt-dlp es el componente que entiende las páginas de video. Los sitios cambian a
menudo y una versión vieja deja de reconocerlos, así que Geas puede comprobar
la última versión publicada (PyPI) y actualizarla:
  - desde el código fuente, con pip en su propio entorno de Python;
  - instalada (Geas.exe, sin pip), descargando el paquete oficial de PyPI a
    %APPDATA%\\Geas\\yt-dlp, que al abrir Geas tiene prioridad sobre el incluido.
Después hay que reiniciar Geas: yt-dlp carga partes de sí mismo a medida que
las usa y no debe mezclar las de dos versiones.
"""
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from importlib import metadata

import network
import paths

PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
DOWNLOAD_DIR = paths.data("yt-dlp")  # yt-dlp descargado por Geas instalada (contiene la carpeta yt_dlp)


class _DownloadedYtDlpFinder(importlib.abc.MetaPathFinder):
    """Importa yt_dlp desde DOWNLOAD_DIR antes que la copia incluida en Geas.exe."""

    def find_spec(self, name, path=None, target=None):
        if name == "yt_dlp":
            return importlib.machinery.PathFinder.find_spec(name, [DOWNLOAD_DIR], target)
        if name.startswith("yt_dlp."):
            return importlib.machinery.PathFinder.find_spec(name, path, target)  # path: el del paquete de arriba
        return None


def _downloaded_version():
    """Versión del yt-dlp descargado (leída del disco), o None si no hay uno."""
    try:
        with open(os.path.join(DOWNLOAD_DIR, "yt_dlp", "version.py"), encoding="utf-8") as f:
            match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", f.read())
        return match.group(1) if match else None
    except OSError:
        return None


def use_downloaded_copy():
    """Al abrir Geas instalada: si hay un yt-dlp descargado, se usa ese (debe llamarse antes de importarlo)."""
    if paths.FROZEN and _downloaded_version():
        sys.meta_path.insert(0, _DownloadedYtDlpFinder())


def installed_version():
    """Versión que usará Geas al abrirse (la del disco, aunque se acabe de actualizar)."""
    if paths.FROZEN:
        downloaded = _downloaded_version()
        if downloaded:
            return downloaded
        try:
            from yt_dlp.version import __version__
            return __version__
        except ImportError:
            return None
    importlib.invalidate_caches()
    try:
        return metadata.version("yt-dlp")
    except metadata.PackageNotFoundError:
        return None


def _pypi_info(timeout=10):
    request = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json", "User-Agent": "Geas"})
    with urllib.request.urlopen(request, timeout=timeout, context=network.ssl_context()) as response:
        return json.load(response)


def latest_version(timeout=10):
    """Última versión publicada. Lanza una excepción si no hay conexión."""
    return _pypi_info(timeout)["info"]["version"]


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


def _download_update(timeout=120):
    """Geas instalada: baja el paquete oficial (wheel) de PyPI, comprueba su SHA-256 y lo deja listo."""
    info = _pypi_info()
    version = info["info"]["version"]
    wheel = next((f for f in info["urls"]
                  if f.get("packagetype") == "bdist_wheel" and f["filename"].endswith("-py3-none-any.whl")), None)
    if wheel is None:
        return False, f"PyPI no tiene un paquete de yt-dlp {version} para descargar"
    request = urllib.request.Request(wheel["url"], headers={"User-Agent": "Geas"})
    with urllib.request.urlopen(request, timeout=timeout, context=network.ssl_context()) as response:
        blob = response.read()
    if hashlib.sha256(blob).hexdigest() != wheel["digests"]["sha256"]:
        return False, "El archivo descargado no coincide con el publicado (SHA-256): no se instaló"

    staging, previous = DOWNLOAD_DIR + ".nuevo", DOWNLOAD_DIR + ".anterior"
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(staging, [name for name in archive.namelist() if name.startswith("yt_dlp/")])
    shutil.rmtree(previous, ignore_errors=True)
    if os.path.isdir(DOWNLOAD_DIR):
        os.replace(DOWNLOAD_DIR, previous)
    os.replace(staging, DOWNLOAD_DIR)
    shutil.rmtree(previous, ignore_errors=True)
    return True, f"yt-dlp {version} descargado de PyPI ({wheel['filename']}, SHA-256 verificado)"


def run_update(timeout=600):
    """Actualiza yt-dlp. Devuelve (correcto, detalle para el registro)."""
    if paths.FROZEN:
        try:
            return _download_update()
        except Exception as e:
            return False, str(e)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(update_command(), capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return result.returncode == 0, (result.stdout + "\n" + result.stderr).strip()
