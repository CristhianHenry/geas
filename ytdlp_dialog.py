# ytdlp_dialog.py - "Actualizar yt-dlp": versión instalada, última publicada y actualización
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QProgressBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

import icons
import ytdlp_updater


class VersionCheckThread(QThread):
    """Consulta la última versión publicada sin bloquear la interfaz."""
    checked = pyqtSignal(str, str)  # (última versión, error)

    def run(self):
        try:
            self.checked.emit(ytdlp_updater.latest_version(), "")
        except Exception as e:
            self.checked.emit("", str(e))


class UpdateThread(QThread):
    done = pyqtSignal(bool, str)  # (correcto, salida de pip)

    def run(self):
        self.done.emit(*ytdlp_updater.run_update())


class YtDlpUpdateDialog(QDialog):
    """Ventana propia (no modal, como el Programador): puede cerrarse mientras se actualiza."""
    restart_requested = pyqtSignal()
    updated = pyqtSignal(str)  # versión nueva instalada
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actualizar yt-dlp")
        self.setWindowIcon(icons.icon("redownload"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(480)
        self.installed = None
        self.updating = False
        self.check_thread = None
        self.update_thread = None

        layout = QVBoxLayout(self)
        title = QLabel("yt-dlp")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        explanation = QLabel("Es el componente que reconoce los videos de las páginas. Los sitios cambian a "
                             "menudo: si un video deja de detectarse o de descargarse, actualízalo.")
        explanation.setObjectName("Hint")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(12)
        for row, text in enumerate(("Versión instalada:", "Última versión:")):
            label = QLabel(text)
            label.setObjectName("FieldName")
            grid.addWidget(label, row, 0, Qt.AlignRight)
        self.installed_value = QLabel()
        self.latest_value = QLabel()
        grid.addWidget(self.installed_value, 0, 1)
        grid.addWidget(self.latest_value, 1, 1)
        layout.addLayout(grid)

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)  # sin porcentaje: pip no lo informa
        self.busy.setTextVisible(False)
        self.busy.hide()
        layout.addWidget(self.busy)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.message)

        buttons = QHBoxLayout()
        self.update_button = QPushButton(icons.icon("redownload"), "Actualizar ahora")
        self.update_button.setObjectName("PrimaryButton")
        self.update_button.clicked.connect(self.start_update)
        self.restart_button = QPushButton("Reiniciar Geas")
        self.restart_button.clicked.connect(self.restart_requested.emit)
        self.restart_button.hide()
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.hide)
        buttons.addWidget(self.update_button)
        buttons.addWidget(self.restart_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.refresh_installed()

    def refresh_installed(self):
        self.installed = ytdlp_updater.installed_version()
        self.installed_value.setText(self.installed or "no instalado")

    def check(self):
        """Consulta la última versión (cada vez que se abre la ventana)."""
        if self.updating or (self.check_thread is not None and self.check_thread.isRunning()):
            return
        self.latest_value.setText("comprobando…")
        self.update_button.setEnabled(False)
        self.check_thread = VersionCheckThread(self)
        self.check_thread.checked.connect(self.on_checked)
        self.check_thread.start()

    def on_checked(self, latest, error):
        if self.updating:
            return
        if error:
            self.latest_value.setText("no se pudo comprobar")
            self._set_message(f"Sin conexión con el servidor de yt-dlp ({error}). Puedes intentar actualizar igual.",
                              "Warning")
            self.update_button.setEnabled(True)
            return
        self.latest_value.setText(latest)
        if ytdlp_updater.is_newer(latest, self.installed):
            self._set_message("Hay una versión nueva.")
            self.update_button.setEnabled(True)
        elif not self.restart_button.isVisible():
            self._set_message("Ya tienes la última versión.")

    def start_update(self):
        self.updating = True
        self.update_button.setEnabled(False)
        self.busy.show()
        self._set_message("Actualizando… (puede tardar un minuto)")
        self.log.emit("Actualizando yt-dlp…")
        self.update_thread = UpdateThread(self)
        self.update_thread.done.connect(self.on_updated)
        self.update_thread.start()

    def on_updated(self, ok, output):
        self.updating = False
        self.busy.hide()
        before = self.installed
        self.refresh_installed()
        if ok and self.installed != before:
            self._set_message(f"yt-dlp se actualizó a la versión {self.installed}. "
                              f"Reinicia Geas para empezar a usarla.")
            self.restart_button.show()
            self.restart_button.setDefault(True)
            self.log.emit(f"yt-dlp actualizado: {before} → {self.installed}")
            self.updated.emit(self.installed)
        elif ok:
            self._set_message("Ya tenías la última versión.")
            self.log.emit("yt-dlp ya estaba en la última versión")
        else:
            lines = [line for line in output.splitlines() if line.strip()]
            self._set_message(f"No se pudo actualizar: {lines[-1] if lines else 'error desconocido'}", "Error")
            self.update_button.setEnabled(True)
            self.log.emit(f"No se pudo actualizar yt-dlp:\n{output}")

    def _set_message(self, text, object_name=""):
        self.message.setText(text)
        if self.message.objectName() != object_name:
            # El color sale de style.qss (QLabel#Warning / #Error): hay que volver a aplicar el estilo
            self.message.setObjectName(object_name)
            self.message.style().unpolish(self.message)
            self.message.style().polish(self.message)
