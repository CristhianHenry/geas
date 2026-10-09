# app_update_dialog.py - "Buscar actualizaciones de Geas": versión nueva, novedades e instalación
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QPlainTextEdit
from PySide6.QtCore import Qt, QThread, Signal

import app_updater
import icons
from ui_format import format_size
from version import __version__


class ReleaseCheckThread(QThread):
    checked = Signal(object, str)  # (versión publicada o None, error)

    def run(self):
        try:
            self.checked.emit(app_updater.latest_release(), "")
        except Exception as e:
            self.checked.emit(None, str(e))


class InstallerDownloadThread(QThread):
    progress = Signal(int, int)
    done = Signal(str, str)  # (ruta del instalador, error)

    def __init__(self, release):
        super().__init__()
        self.release = release

    def run(self):
        try:
            self.done.emit(app_updater.download(self.release, self.progress.emit), "")
        except Exception as e:
            self.done.emit("", str(e))


class AppUpdateDialog(QDialog):
    """Consulta la última versión; si hay una nueva, la descarga y pide a Geas que la instale."""
    install_requested = Signal(str)  # ruta del instalador ya descargado y verificado

    def __init__(self, parent=None, release=None):
        super().__init__(parent)
        self.setWindowTitle("Actualizar Geas")
        self.setWindowIcon(icons.icon("app"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(520)
        self.release = None
        self._threads = []

        layout = QVBoxLayout(self)
        self.title = QLabel(f"Tienes Geas {__version__}. Buscando una versión nueva…")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.hide()
        layout.addWidget(self.notes)
        self.bar = QProgressBar()
        self.bar.hide()
        layout.addWidget(self.bar)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.update_button = QPushButton(icons.icon("redownload"), "Actualizar ahora")
        self.update_button.setObjectName("PrimaryButton")
        self.update_button.setEnabled(False)
        self.update_button.clicked.connect(self.start_download)
        self.close_button = QPushButton("Más tarde")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.update_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        if release is not None:
            self._show_release(release, "")
        else:
            self._start(ReleaseCheckThread(), "checked", self._show_release)

    def _start(self, thread, signal, slot):
        self._threads.append(thread)  # Qt no debe destruirlo mientras corre
        getattr(thread, signal).connect(slot)
        thread.start()

    def _show_release(self, release, error):
        if error:
            self.title.setText(f"No se pudo consultar si hay una versión nueva:\n{error}")
            return
        if not app_updater.is_update(release):
            self.title.setText(f"Tienes la última versión de Geas ({__version__}).")
            self.close_button.setText("Cerrar")
            return
        self.release = release
        size = f" ({format_size(release['size'])})" if release["size"] else ""
        self.title.setText(f"Geas {release['version']} está disponible{size}. Tienes la {__version__}.\n"
                           f"Las descargas en curso se detienen un momento y siguen solas al volver a abrir.")
        if release["notes"].strip():
            self.notes.setPlainText(release["notes"].strip())
            self.notes.show()
        self.update_button.setEnabled(True)

    def start_download(self):
        self.update_button.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        thread = InstallerDownloadThread(self.release)
        thread.progress.connect(self._on_progress)
        self._start(thread, "done", self._on_downloaded)

    def _on_progress(self, done, total):
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done / total * 1000))

    def _on_downloaded(self, path, error):
        if error:
            self.bar.hide()
            self.title.setText(f"No se pudo descargar la actualización:\n{error}")
            self.update_button.setEnabled(True)
            return
        self.install_requested.emit(path)
        self.accept()
