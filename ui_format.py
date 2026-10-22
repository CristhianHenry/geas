# ui_format.py - Formato de tamaños, velocidades y tiempos para la interfaz (estilo es-ES)
import re
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
    "en espera": "Pendiente",  # "Descargar más tarde": no empieza sola
    "en cola": "En cola",
    "cancelado": "Cancelado",
    "interrumpida": "Interrumpida",
    "Procesando/Convirtiendo...": "Procesando…",
}


# Errores frecuentes: (texto a buscar en el detalle técnico, explicación con lo que se puede hacer)
_ERRORS = [
    ("Sign in to confirm", "YouTube pide confirmar que no eres un robot: descárgalo desde el navegador, con la extensión"),
    ("Private video", "El video es privado"),
    ("Video unavailable", "El video ya no está disponible"),
    ("This video is not available", "El video no está disponible en tu país o fue borrado"),
    ("members-only", "El video es solo para miembros del canal"),
    ("Requested format is not available", "Esa calidad ya no está disponible: vuelve a elegirla"),
    ("Unsupported URL", "Geas no reconoce videos en ese sitio"),
    ("unable to continue", "El sitio dejó de entregar una parte del video: pulsa Reanudar para seguir desde donde quedó"),
    ("ffmpeg", "Falta ffmpeg para unir el video y el audio (Opciones → Video)"),
    ("espacio insuficiente", "No hay espacio suficiente en el disco"),
    ("401", "El sitio pide usuario y contraseña: agrégalos en Opciones → Proxy y sitios"),
    ("403", "El servidor negó el acceso: el enlace pudo vencer (usa Actualizar dirección de descarga)"),
    ("404", "El archivo ya no existe en el servidor"),
    ("410", "El enlace venció: usa Actualizar dirección de descarga"),
    ("416", "El servidor no deja continuar desde donde quedó: descárgalo de nuevo"),
    ("429", "El sitio está limitando las descargas: espera unos minutos y reanuda"),
    ("502", "El servidor del sitio está saturado o caído: espera un rato y reanuda"),
    ("503", "El servidor del sitio está saturado o caído: espera un rato y reanuda"),
    ("NameResolution", "Sin conexión a internet, o el sitio no existe"),
    ("getaddrinfo", "Sin conexión a internet, o el sitio no existe"),
    ("Failed to resolve", "Sin conexión a internet, o el sitio no existe"),
    ("timed out", "El servidor tardó demasiado en responder: reanuda para intentar de nuevo"),
    ("Timeout", "El servidor tardó demasiado en responder: reanuda para intentar de nuevo"),
    ("ProxyError", "No se pudo usar el proxy: revisa Opciones → Proxy y sitios"),
    ("SSLError", "La conexión segura con el sitio falló (certificado)"),
    ("Connection", "Se cortó la conexión con el servidor: reanuda para seguir desde donde quedó"),
    ("descarga incompleta", "La descarga quedó incompleta: reanuda para seguir desde donde quedó"),
]


def friendly_error(detail):
    """Explicación de un error para cualquier usuario (el detalle técnico va al registro y al tooltip)."""
    detail = detail or ""
    for needle, text in _ERRORS:
        if needle.isdigit():
            # Códigos HTTP: "403" suelto o "HTTP Error 403" / "403 Client Error"; no dentro de otro
            # número ni el número de un pedacito ("fragment 416 not found" no es un error 416)
            if re.search(rf"(?<!\d)(?<!fragment )(?<!Frag){needle}(?!\d)", detail, re.IGNORECASE):
                return text
        elif needle.lower() in detail.lower():
            return text
    detail = detail.strip(" :")
    return detail[:120] if detail else "Algo falló"


def describe_status(status):
    """Estado interno ('descargando', 'error: ...', 'completado (aviso)') como texto para la interfaz."""
    status = status or ""
    if status.startswith("completado"):
        return "Completado" + status[len("completado"):]
    if status.startswith("error"):
        return "Error: " + friendly_error(status[len("error"):])
    if status.startswith("convirtiendo"):
        return "C" + status[1:]
    return _STATUS_TEXT.get(status, status[:1].upper() + status[1:])
