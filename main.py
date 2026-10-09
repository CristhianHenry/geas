#main.py
import os
import sys

# Los recursos (style.qss, iconos, historial) se buscan junto al programa,
# aunque lo inicie el navegador o un acceso directo desde otra carpeta
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTranslator, QLibraryInfo
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
    if translator.load("qtbase_es", QLibraryInfo.location(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    window = DownloadApp()
    window.show()
    sys.exit(app.exec_())
