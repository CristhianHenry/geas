# app_updater.py - Actualizaciones de Geas desde las "Releases" de su repositorio de GitHub
"""
Cada versión publicada lleva su instalador (Geas-Setup-<versión>.exe). Geas lo
descarga, comprueba su SHA-256 (GitHub lo publica junto a cada archivo) y lo
ejecuta sin preguntas: el instalador reemplaza el programa y vuelve a abrir
Geas, que retoma las descargas que se detuvieron.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

import paths
from version import __version__, UPDATE_REPO
from ytdlp_updater import is_newer

_INSTALLER = re.compile(r"^Geas-Setup-[\d.]+\.exe$", re.IGNORECASE)


def enabled():
    """Solo la versión instalada se actualiza así (desde el código se usa git)."""
    return bool(UPDATE_REPO) and paths.FROZEN


def _open(url, timeout):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Geas"})
    return urllib.request.urlopen(request, timeout=timeout)


def latest_release(timeout=10):
    """
    Última versión publicada: {'version', 'url', 'size', 'sha256', 'notes', 'page'},
    o None si no tiene instalador. Lanza una excepción si no hay conexión.
    """
    with _open(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest", timeout) as response:
        data = json.load(response)
    asset = next((a for a in data.get("assets", []) if _INSTALLER.match(a.get("name", ""))), None)
    if asset is None:
        return None
    digest = asset.get("digest") or ""
    return {
        "version": (data.get("tag_name") or "").lstrip("vV"),
        "url": asset["browser_download_url"],
        "size": asset.get("size") or 0,
        "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None,
        "notes": data.get("body") or "",
        "page": data.get("html_url") or "",
    }


def is_update(release):
    return bool(release) and is_newer(release["version"], __version__)


def download(release, progress=None, timeout=60):
    """Descarga el instalador a la carpeta temporal y devuelve su ruta. progress(bajados, total)."""
    path = os.path.join(tempfile.gettempdir(), f"Geas-Setup-{release['version']}.exe")
    partial = path + ".part"
    digest = hashlib.sha256()
    done = 0
    with _open(release["url"], timeout) as response, open(partial, "wb") as f:
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, release["size"])
    if release["sha256"] and digest.hexdigest() != release["sha256"]:
        os.remove(partial)
        raise ValueError("El instalador descargado no coincide con el publicado (SHA-256): no se usará")
    os.replace(partial, path)
    return path


def run_installer(path):
    """Instala sin preguntas; al terminar, el instalador vuelve a abrir Geas."""
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], close_fds=True, creationflags=flags)
