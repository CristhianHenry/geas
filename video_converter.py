# video_converter.py - Conversión a H.264 de los videos que el Reproductor de Windows no abre
"""
Windows (sin extensiones de la Microsoft Store) no reproduce AV1, VP9 ni HEVC.
Tras descargar un video en esos formatos, Geas puede convertirlo a H.264 de
8 bits: lo abren el Reproductor de Windows, teles y móviles.

Primero se usa el codificador de la tarjeta gráfica (NVIDIA, Intel Quick Sync,
AMD o el de Windows), varias veces más rápido; el primero que funcione en esta
PC se averigua con una prueba corta. Si no hay o falla, se usa el procesador.
"""

import logging
import os
import subprocess
import sys
import threading
from typing import Callable, Optional

from media_handler import find_ffmpeg

logger = logging.getLogger(__name__)

# Códecs que el Reproductor de Windows no trae de serie
INCOMPATIBLE_CODECS = {"av1", "vp9", "vp8", "hevc"}

# Opciones → Video: probar primero la tarjeta gráfica (Geas lo fija al abrir y al cambiar Opciones)
use_hardware = True

# Codificadores por hardware, en orden: (códec de ffmpeg, quién convierte, opciones). {bitrate} se
# completa según la altura del video. Quick Sync va dos veces: con calidad constante (Intel de 4.ª
# generación en adelante) y con tasa de bits (las anteriores, como los HD 4000).
_HARDWARE = [
    ("h264_nvenc", "NVIDIA", ["-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0", "-pix_fmt", "yuv420p"]),
    ("h264_qsv", "Intel Quick Sync", ["-preset", "medium", "-global_quality", "23", "-pix_fmt", "nv12"]),
    ("h264_qsv", "Intel Quick Sync", ["-preset", "medium", "-b:v", "{bitrate}", "-pix_fmt", "nv12"]),
    ("h264_amf", "AMD", ["-quality", "balanced", "-rc", "cqp", "-qp_i", "22", "-qp_p", "24", "-pix_fmt", "nv12"]),
    ("h264_mf", "la gráfica", ["-hw_encoding", "1", "-b:v", "{bitrate}", "-pix_fmt", "nv12"]),
]
_hardware_choice = None   # el que funcionó en esta PC (se averigua una vez por sesión)
_hardware_checked = False
_hardware_lock = threading.Lock()  # dos conversiones a la vez: una sola prueba

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
    """Códec de video, altura y duración (segundos) del archivo, o None si no se puede leer."""
    ffprobe = _tool("ffprobe")
    if not ffprobe or not os.path.isfile(path):
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,height:format=duration", "-of", "default=noprint_wrappers=1", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_CREATION_FLAGS)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if not values.get("codec_name"):
        return None
    try:
        duration = float(values.get("duration", 0))
    except ValueError:
        duration = 0.0
    height = int(values["height"]) if values.get("height", "").isdigit() else 0
    return {"codec": values["codec_name"].lower(), "duration": duration, "height": height}


def needs_h264(path: str) -> bool:
    """True si el video está en un códec que el Reproductor de Windows no abre."""
    info = probe_video(path)
    return bool(info) and info["codec"] in INCOMPATIBLE_CODECS


def _bitrate(height: int) -> str:
    """Tasa de bits para los codificadores que la necesitan, según la altura del video."""
    for limit, rate in ((480, "2500k"), (720, "5M"), (1080, "8M"), (1440, "16M")):
        if height and height <= limit:
            return rate
    return "35M" if height else "8M"


def _software_encoder():
    """libx264 en el procesador. Con pocos núcleos, un ajuste 2-3 veces más rápido (archivo algo más grande)."""
    preset = "veryfast" if (os.cpu_count() or 2) <= 4 else "fast"
    return ("libx264", "el procesador",
            ["-preset", preset, "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.1"])


def _encoder_works(ffmpeg: str, codec: str, args: list) -> bool:
    """Prueba corta con un video generado: ¿este codificador funciona en esta PC (driver, chip)?"""
    test = [ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=1280x720:r=30:d=1",
            "-c:v", codec, *[a.replace("{bitrate}", "5M") for a in args], "-f", "null", "-"]
    try:
        return subprocess.run(test, capture_output=True, timeout=30, creationflags=_CREATION_FLAGS).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def hardware_encoder(ffmpeg: str):
    """El primer codificador de la tarjeta gráfica que funciona en esta PC, o None (se averigua una vez)."""
    global _hardware_checked
    with _hardware_lock:
        if not _hardware_checked:
            _hardware_checked = True
            _detect_hardware(ffmpeg)
    return _hardware_choice


def _detect_hardware(ffmpeg: str):
    global _hardware_choice
    listed = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", creationflags=_CREATION_FLAGS).stdout
    for codec, label, args in _HARDWARE:
        if f" {codec} " in listed and _encoder_works(ffmpeg, codec, args):
            _hardware_choice = (codec, label, args)
            logger.info(f"Conversión a H.264 con la tarjeta gráfica: {codec}")
            return
    logger.info("Sin codificador H.264 por hardware: se convierte con el procesador")


def convert_to_h264(path: str, progress_callback: Callable[[float], None] = None,
                    is_cancelled: Callable[[], bool] = None,
                    encoder_callback: Callable[[str], None] = None) -> str:
    """
    Convierte el video a H.264 en el mismo archivo. Se escribe primero en un
    archivo temporal y solo reemplaza al original si la conversión terminó bien.
    El audio y los subtítulos se copian. Devuelve quién convirtió ("NVIDIA",
    "el procesador"...); encoder_callback lo recibe al empezar cada intento.
    """
    global _hardware_choice
    ffmpeg = _tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg no está instalado")
    info = probe_video(path) or {"duration": 0, "height": 0}
    attempts = []
    if use_hardware and hardware_encoder(ffmpeg):
        attempts.append(_hardware_choice)
    attempts.append(_software_encoder())
    for index, (codec, label, args) in enumerate(attempts):
        if encoder_callback:
            encoder_callback(label)
        args = [a.replace("{bitrate}", _bitrate(info.get("height"))) for a in args]
        try:
            _encode(ffmpeg, path, codec, args, info, progress_callback, is_cancelled)
            return label
        except RuntimeError as e:
            if index == len(attempts) - 1:
                raise
            # La gráfica pasó la prueba pero no pudo con este video: el procesador lo intenta, y por el
            # resto de la sesión ya no se usa la gráfica
            logger.warning(f"{label} no pudo convertir {os.path.basename(path)} ({e}); se usa el procesador")
            _hardware_choice = None


def _encode(ffmpeg, path, codec, args, info, progress_callback, is_cancelled):
    temp = os.path.splitext(path)[0] + ".convirtiendo.mp4"
    command = [
        ffmpeg, "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
        "-i", path, "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
        "-c:v", codec, *args,
        "-c:a", "copy", "-c:s", "mov_text", "-movflags", "+faststart", temp,
    ]
    logger.info(f"Convirtiendo a H.264 con {codec}: {os.path.basename(path)}")
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
