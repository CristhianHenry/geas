# paths.py - Dónde están los recursos de Geas y dónde guarda sus datos
"""
Desde el código fuente todo queda en la carpeta del proyecto, como siempre.
Instalada (Geas.exe, hecho con PyInstaller), los recursos van con el programa
y los datos del usuario (opciones, historial, registro, yt-dlp actualizado)
en %APPDATA%\\Geas: la carpeta del programa se reemplaza en cada actualización.
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))

# Carpeta del programa (Geas.exe y geas-host.exe) o del proyecto
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
# Recursos de solo lectura (style.qss, branding/): PyInstaller los deja en _internal
RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Geas") if FROZEN else APP_DIR
os.makedirs(DATA_DIR, exist_ok=True)


def resource(*parts):
    return os.path.join(RESOURCE_DIR, *parts)


def data(*parts):
    return os.path.join(DATA_DIR, *parts)
