# ui_format.py - Formato de tamaños, velocidades y tiempos para la interfaz (estilo es-ES)
from datetime import datetime


def _decimal(value, decimals=2):
    return f"{value:.{decimals}f}".replace(".", ",")


def format_size(size):
    """1536 -> '1,50 KB'; 0 o desconocido -> ''"""
    if not size:
        return ""
    size = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{_decimal(size)} {unit}"
        size /= 1024


def format_speed(bytes_per_second):
    if not bytes_per_second:
        return ""
    return f"{format_size(bytes_per_second)}/s"


def format_eta(seconds):
    """Tiempo restante como en IDM: '45 s', '3 min 20 s', '1 h 05 min'"""
    if seconds is None or seconds < 0:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def format_date(timestamp):
    """'2026-10-06T15:06:40' -> '06/10/2026 15:06'"""
    try:
        return datetime.fromisoformat(timestamp).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return timestamp or ""


def format_percent(value):
    return f"{_decimal(value, 1)} %"


_STATUS_TEXT = {
    "descargando": "Recibiendo datos…",
    "obteniendo información": "Conectando…",
    "esperando": "Conectando…",
    "pausado": "En pausa",
    "en espera": "En espera",
    "en cola": "En cola",
    "cancelado": "Cancelado",
    "interrumpida": "Interrumpida",
    "Procesando/Convirtiendo...": "Procesando…",
}


def describe_status(status):
    """Estado interno ('descargando', 'error: ...', 'completado (aviso)') como texto para la interfaz."""
    status = status or ""
    if status.startswith("completado"):
        return "Completado" + status[len("completado"):]
    if status.startswith("error"):
        return "Error" + status[len("error"):]
    if status.startswith("convirtiendo"):
        return "C" + status[1:]
    return _STATUS_TEXT.get(status, status[:1].upper() + status[1:])
