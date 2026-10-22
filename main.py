#main.py
import faulthandler
import os
import sys
from datetime import datetime

import network
import paths
import ytdlp_updater
from version import __version__

# Antes de cualquier conexión: Geas confía solo en sus certificados (certifi), no en listas ajenas
network.pin_trust_store()

# Si Geas muere por un fallo nativo (Python, Qt), geas.log no alcanza a registrar nada: faulthandler
# deja en crash.log la pila de Python de cada hilo. El archivo debe quedar abierto mientras Geas viva.
_crash_log_path = paths.data("crash.log")
_crash_log_big = os.path.exists(_crash_log_path) and os.path.getsize(_crash_log_path) > 1_000_000
_crash_log = open(_crash_log_path, "w" if _crash_log_big else "a", encoding="utf-8")
_crash_log.write(f"--- Geas {__version__}, Python {sys.version.split()[0]}, {datetime.now():%Y-%m-%d %H:%M:%S}\n")
_crash_log.flush()
faulthandler.enable(file=_crash_log, all_threads=True)

# Los archivos relativos se buscan en la carpeta de datos, aunque lo inicie el
# navegador o un acceso directo desde otra carpeta
os.chdir(paths.DATA_DIR)
# Instalada: el yt-dlp descargado con "Actualizar yt-dlp" se usa en vez del incluido
ytdlp_updater.use_downloaded_copy()

if sys.platform == "win32":
    # Icono y nombre propios en la barra de tareas y en los avisos de Windows (no los de Python)
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Geas.DownloadManager")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTranslator, QLibraryInfo
from gui import DownloadApp


def wait_for_previous_instance():
    """
    Al reiniciar (p. ej. tras actualizar yt-dlp) la instancia anterior aún se
    está cerrando: se espera a que suelte el puerto de la extensión y el registro.
    """
    if "--restart-from" not in sys.argv:
        return
    index = sys.argv.index("--restart-from")
    try:
        pid = int(sys.argv[index + 1])
    except (IndexError, ValueError):
        pid = None
    del sys.argv[index:index + 2]
    if pid and sys.platform == "win32":
        import ctypes
        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, 15000)
            ctypes.windll.kernel32.CloseHandle(handle)


if __name__ == "__main__":
    wait_for_previous_instance()
    app = QApplication(sys.argv)
    # Botones y diálogos estándar de Qt en español ("Sí", "No", "Supr", selector de archivos...)
    translator = QTranslator()
    if translator.load("qtbase_es", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    window = DownloadApp()
    window.show()
    sys.exit(app.exec())
