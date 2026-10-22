# ffmpeg_setup.py - Geas descarga ffmpeg sola la primera vez (sin winget ni pasos a mano)
"""
ffmpeg une el video y el audio de YouTube en alta calidad, convierte a H.264 e
incrusta subtítulos. Si el equipo no lo tiene, Geas baja la compilación
"essentials" de gyan.dev (la que enlaza ffmpeg.org para Windows) desde su copia
oficial en GitHub, comprueba su SHA-256 y deja ffmpeg.exe y ffprobe.exe en la
carpeta del programa, donde find_ffmpeg() ya los busca. Se hace una sola vez.
"""
import hashlib
import json
import logging
import os
import re
import urllib.request
import zipfile

from PySide6.QtCore import QObject, QThread, Signal

import network
import paths
from media_handler import find_ffmpeg

GITHUB_RELEASE = "https://api.github.com/repos/GyanD/codexffmpeg/releases/latest"
GYAN_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"  # si GitHub no responde
TARGET_DIR = os.path.join(paths.APP_DIR, "ffmpeg", "bin")
TOOLS = ("ffprobe.exe", "ffmpeg.exe")  # ffmpeg.exe al final: si está, ffprobe.exe también
_ESSENTIALS = re.compile(r"^ffmpeg-[\d.]+-essentials_build\.zip$")


class Cancelled(Exception):
    pass


def explain(error):
    """El motivo en palabras simples (los ValueError de este módulo ya vienen explicados)."""
    text = str(error) or error.__class__.__name__
    if isinstance(error, ValueError):
        return text
    if isinstance(error, PermissionError):
        return f"Windows no dejó guardarlo en {TARGET_DIR}"
    if "getaddrinfo" in text or "NameResolution" in text:
        return "sin conexión a internet"
    if "timed out" in text.lower():
        return "el servidor tardó demasiado en responder"
    return text


def _open(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "Geas", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=timeout, context=network.ssl_context())


def latest_build(timeout=15):
    """{'url', 'size', 'sha256'} del zip "essentials" más reciente. Lanza una excepción si no hay conexión."""
    try:
        with _open(GITHUB_RELEASE, timeout) as response:
            data = json.load(response)
        asset = next(a for a in data.get("assets", []) if _ESSENTIALS.match(a.get("name", "")))
        digest = asset.get("digest") or ""
        if digest.startswith("sha256:"):
            return {"url": asset["browser_download_url"], "size": asset.get("size") or 0,
                    "sha256": digest.split(":", 1)[1].lower()}
    except Exception:
        pass
    with _open(GYAN_ZIP + ".sha256", timeout) as response:
        sha256 = response.read().decode("ascii", "replace").split()[0].lower()
    return {"url": GYAN_ZIP, "size": 0, "sha256": sha256}


def install(progress=None, is_cancelled=None, timeout=60):
    """
    Descarga, verifica y deja ffmpeg en TARGET_DIR; devuelve esa carpeta.
    progress(bajados, total); is_cancelled() corta la descarga (lanza Cancelled).
    """
    build = latest_build()
    if not re.fullmatch(r"[0-9a-f]{64}", build["sha256"]):
        raise ValueError("no se pudo comprobar la descarga de ffmpeg (falta su SHA-256)")
    os.makedirs(TARGET_DIR, exist_ok=True)
    partial = os.path.join(os.path.dirname(TARGET_DIR), "ffmpeg.zip.part")
    digest = hashlib.sha256()
    try:
        with _open(build["url"], timeout) as response, open(partial, "wb") as f:
            total = build["size"] or int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if is_cancelled and is_cancelled():
                    raise Cancelled()
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if digest.hexdigest() != build["sha256"]:
            raise ValueError("el ffmpeg descargado no coincide con el publicado (SHA-256): no se usará")
        with zipfile.ZipFile(partial) as archive:
            names = archive.namelist()
            for tool in TOOLS:
                member = next((n for n in names if n.lower().endswith("/bin/" + tool)), None)
                if member is None:
                    raise ValueError(f"el paquete de ffmpeg no trae {tool}")
                destination = os.path.join(TARGET_DIR, tool)
                with archive.open(member) as source, open(destination + ".new", "wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                os.replace(destination + ".new", destination)
    finally:
        for leftover in [partial] + [os.path.join(TARGET_DIR, t + ".new") for t in TOOLS]:
            if os.path.exists(leftover):
                os.remove(leftover)
    return TARGET_DIR


class _InstallThread(QThread):
    progress = Signal(object, object)  # (bajados, total): pueden pasar de 2 GB en int de 32 bits
    done = Signal(str, str)            # (carpeta, error)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancelled = False

    def run(self):
        try:
            self.done.emit(install(self.progress.emit, lambda: self.cancelled), "")
        except Cancelled:
            self.done.emit("", "cancelada")
        except Exception as e:
            logging.getLogger(__name__).warning(f"No se pudo descargar ffmpeg: {e!r}")
            self.done.emit("", explain(e))


class FfmpegSetup(QObject):
    """Estado de la descarga de ffmpeg, compartido por la barra de estado y Primeros pasos."""
    changed = Signal()
    installed = Signal(str)  # carpeta de ffmpeg recién descargado

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.done = self.total = 0
        self.error = ""

    @property
    def busy(self):
        return self.thread is not None

    def ensure(self):
        """Empieza a descargar ffmpeg si no está en el equipo (y no se está bajando ya)."""
        if self.busy or find_ffmpeg():
            return
        self.done = self.total = 0
        self.error = ""
        self.thread = _InstallThread(self)
        self.thread.progress.connect(self._on_progress)
        self.thread.done.connect(self._on_done)
        self.thread.start()
        self.changed.emit()

    def cancel(self):
        if self.thread is not None:
            self.thread.cancelled = True
            self.thread.wait(5000)

    def percent(self):
        return int(self.done * 100 / self.total) if self.total else None

    def _on_progress(self, done, total):
        previous = self.percent()
        self.done, self.total = done, total
        if self.percent() != previous:
            self.changed.emit()

    def _on_done(self, folder, error):
        self.thread = None
        self.error = error
        self.changed.emit()
        if folder:
            self.installed.emit(folder)
