# video_converter.py - Conversión a H.264 de los videos que el Reproductor de Windows no abre
"""
Windows (sin extensiones de la Microsoft Store) no reproduce AV1, VP9 ni HEVC.
Tras descargar un video en esos formatos, Geas puede convertirlo a H.264 de
8 bits (High 4.1): lo abren el Reproductor de Windows, teles y móviles.
"""

import logging
import os
import subprocess
import sys
from typing import Callable, Optional

from media_handler import find_ffmpeg

logger = logging.getLogger(__name__)

# Códecs que el Reproductor de Windows no trae de serie
INCOMPATIBLE_CODECS = {"av1", "vp9", "vp8", "hevc"}

# En Windows, sin ventana de consola y con prioridad baja (el equipo sigue respondiendo)
_CREATION_FLAGS = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if sys.platform == "win32" else 0


class ConversionCancelled(Exception):
    """El usuario canceló o pausó la descarga durante la conversión."""


def _tool(name: str) -> Optional[str]:
    folder = find_ffmpeg()
    if not folder:
        return None
    path = os.path.join(folder, f"{name}.exe" if sys.platform == "win32" else name)
    return path if os.path.isfile(path) else None


def probe_video(path: str) -> Optional[dict]:
    """Códec de video y duración (segundos) del archivo, o None si no se puede leer."""
    ffprobe = _tool("ffprobe")
    if not ffprobe or not os.path.isfile(path):
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name:format=duration", "-of", "default=noprint_wrappers=1", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_CREATION_FLAGS)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if not values.get("codec_name"):
        return None
    try:
        duration = float(values.get("duration", 0))
    except ValueError:
        duration = 0.0
    return {"codec": values["codec_name"].lower(), "duration": duration}


def needs_h264(path: str) -> bool:
    """True si el video está en un códec que el Reproductor de Windows no abre."""
    info = probe_video(path)
    return bool(info) and info["codec"] in INCOMPATIBLE_CODECS


def convert_to_h264(path: str, progress_callback: Callable[[float], None] = None,
                    is_cancelled: Callable[[], bool] = None) -> None:
    """
    Convierte el video a H.264 en el mismo archivo. Se escribe primero en un
    archivo temporal y solo reemplaza al original si la conversión terminó bien.
    El audio se copia sin cambios.
    """
    ffmpeg = _tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg no está instalado")
    info = probe_video(path) or {"duration": 0}
    temp = os.path.splitext(path)[0] + ".convirtiendo.mp4"

    command = [
        ffmpeg, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
        "-i", path, "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.1",
        "-c:a", "copy", "-c:s", "mov_text", "-movflags", "+faststart", temp,
    ]
    logger.info(f"Convirtiendo a H.264: {os.path.basename(path)}")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace", creationflags=_CREATION_FLAGS)
    try:
        for line in process.stdout:
            if is_cancelled and is_cancelled():
                process.kill()
                raise ConversionCancelled()
            # "out_time_us" son microsegundos ya convertidos
            if line.startswith("out_time_us=") and info["duration"] and progress_callback:
                microseconds = line.split("=", 1)[1].strip()
                if microseconds.isdigit():
                    progress_callback(min(100.0, int(microseconds) / 1e6 / info["duration"] * 100))
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(process.stderr.read().strip()[-300:] or f"ffmpeg terminó con código {process.returncode}")
        os.replace(temp, path)
        logger.info(f"Conversión terminada: {os.path.basename(path)}")
    finally:
        if process.poll() is None:
            process.kill()
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass


# Códigos de idioma de los subtítulos (ISO 639-1) en los que MP4 espera (ISO 639-2)
_LANGUAGE_CODES = {"es": "spa", "en": "eng", "pt": "por", "fr": "fra", "it": "ita", "de": "deu",
                   "ja": "jpn", "ko": "kor", "zh": "zho", "ru": "rus", "ar": "ara", "hi": "hin"}


def can_embed() -> bool:
    """Incrustar subtítulos requiere ffmpeg; sin él quedan como archivo junto al video."""
    return _tool("ffmpeg") is not None


def embed_subtitles(path: str, subtitle_path: str, language: str = "") -> None:
    """
    Incrusta un archivo de subtítulos (.srt o .vtt) en el MP4, sin recodificar el
    video ni el audio. Los reproductores los muestran como una pista que se activa.
    """
    ffmpeg = _tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg no está instalado")
    temp = os.path.splitext(path)[0] + ".subtitulando.mp4"
    code = _LANGUAGE_CODES.get(language.split("-")[0].lower(), "und")
    command = [ffmpeg, "-y", "-hide_banner", "-v", "error", "-i", path, "-i", subtitle_path,
               "-map", "0", "-map", "1:0", "-c", "copy", "-c:s", "mov_text",
               "-metadata:s:s:0", f"language={code}", "-movflags", "+faststart", temp]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                creationflags=_CREATION_FLAGS)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip()[-300:] or f"ffmpeg terminó con código {result.returncode}")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass
