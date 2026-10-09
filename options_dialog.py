# options_dialog.py - Opciones de Geas (pestañas como en IDM)
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget, QCheckBox,
    QSpinBox, QLineEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QDialogButtonBox
)
from PySide6.QtCore import Qt

import icons
import ytdlp_updater
from media_handler import find_ffmpeg


class OptionsDialog(QDialog):
    def __init__(self, settings, parent=None, update_ytdlp=None):
        super().__init__(parent)
        self.settings = settings
        self.update_ytdlp = update_ytdlp  # abre "Actualizar yt-dlp"
        self.setWindowTitle("Opciones de Geas")
        self.setWindowIcon(icons.icon("options"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(560)

        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._connection_tab(), "Conexión")
        tabs.addTab(self._save_tab(), "Guardar en")
        tabs.addTab(self._video_tab(), "Video")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Aceptar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _check(self, text, key, tooltip=""):
        check = QCheckBox(text)
        check.setChecked(bool(self.settings.get(key)))
        check.setToolTip(tooltip)
        return check

    def _general_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.auto_start = self._check("Iniciar sin preguntar las descargas capturadas del navegador",
                                      "auto_start_downloads",
                                      "Desactívalo para elegir nombre y carpeta antes de cada descarga")
        self.show_progress = self._check("Mostrar la ventana de progreso al iniciar una descarga", "show_progress_dialog")
        self.clipboard = self._check("Detectar enlaces de descarga copiados al portapapeles", "clipboard_monitor")
        self.notifications = self._check("Avisar en la bandeja del sistema al terminar una descarga", "show_notifications")
        self.tray = self._check("Al cerrar la ventana, seguir en la bandeja del sistema", "minimize_to_tray")
        for widget in (self.auto_start, self.show_progress, self.clipboard, self.notifications, self.tray):
            layout.addWidget(widget)
        layout.addStretch()
        return page

    def _connection_tab(self):
        page = QWidget()
        form = QFormLayout(page)
        self.threads = QSpinBox()
        self.threads.setRange(1, 16)
        self.threads.setValue(self.settings.get("default_threads"))
        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(0, 1024 * 1024)
        self.speed_limit.setSuffix(" KB/s")
        self.speed_limit.setSpecialValueText("Sin límite")
        self.speed_limit.setValue(self.settings.get("download_speed_limit_kbps"))
        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(self.settings.get("auto_retry_count"))
        self.max_downloads = QSpinBox()
        self.max_downloads.setRange(1, 10)
        self.max_downloads.setValue(self.settings.get("max_simultaneous_downloads"))
        self.max_downloads.setToolTip("Las demás esperan en la cola y empiezan solas cuando termina una")
        form.addRow("Descargas a la vez:", self.max_downloads)
        form.addRow("Conexiones por descarga:", self.threads)
        form.addRow("Límite de velocidad:", self.speed_limit)
        form.addRow("Reintentos si falla la conexión:", self.retries)
        hint = QLabel("Más conexiones aceleran las descargas en servidores que lo permiten. "
                      "Si un servidor falla con muchas, prueba con 1.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        form.addRow(hint)
        return page

    def _save_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Carpeta donde se guardan las descargas:"))
        row = QHBoxLayout()
        self.folder = QLineEdit(self.settings.get("default_download_folder"))
        browse = QPushButton(icons.icon("folder"), "Examinar…")
        browse.clicked.connect(self.browse_folder)
        row.addWidget(self.folder)
        row.addWidget(browse)
        layout.addLayout(row)
        layout.addStretch()
        return page

    def _video_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.convert = self._check("Convertir a H.264 los videos en AV1, VP9 o HEVC al terminar", "convert_to_h264",
                                   "El Reproductor de Windows, las teles y los móviles abren H.264 sin códecs extra")
        layout.addWidget(self.convert)
        detail = QLabel("La conversión se hace después de descargar, con prioridad baja. Un capítulo de 24 min "
                        "en 1080p tarda unos minutos y el archivo final ocupa algo más.")
        detail.setObjectName("Hint")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        layout.addSpacing(8)
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            layout.addWidget(QLabel("ffmpeg está instalado en:"))
            path = QLineEdit(ffmpeg)
            path.setReadOnly(True)
            path.setCursorPosition(0)
            layout.addWidget(path)
        else:
            status = QLabel("ffmpeg no está instalado: sin él los videos no se reempaquetan ni se convierten.\n"
                            "Instálalo con:  winget install --id Gyan.FFmpeg.Essentials -e")
            status.setObjectName("Warning")
            status.setWordWrap(True)
            status.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(status)

        layout.addSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel(f"yt-dlp {ytdlp_updater.installed_version() or 'no instalado'}"))
        row.addStretch()
        if self.update_ytdlp:
            update = QPushButton(icons.icon("redownload"), "Actualizar yt-dlp…")
            update.clicked.connect(self.update_ytdlp)
            row.addWidget(update)
        layout.addLayout(row)
        self.check_ytdlp = self._check("Avisar cuando haya una versión nueva de yt-dlp (se comprueba una vez al día)",
                                       "check_ytdlp_updates",
                                       "yt-dlp reconoce los videos de las páginas; los sitios cambian a menudo")
        layout.addWidget(self.check_ytdlp)
        layout.addStretch()
        return page

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta", self.folder.text())
        if folder:
            self.folder.setText(os.path.normpath(folder))

    def accept(self):
        values = {
            "default_download_folder": self.folder.text().strip(),
            "default_threads": self.threads.value(),
            "max_simultaneous_downloads": self.max_downloads.value(),
            "download_speed_limit_kbps": self.speed_limit.value(),
            "auto_retry_count": self.retries.value(),
            "auto_start_downloads": self.auto_start.isChecked(),
            "show_progress_dialog": self.show_progress.isChecked(),
            "clipboard_monitor": self.clipboard.isChecked(),
            "show_notifications": self.notifications.isChecked(),
            "minimize_to_tray": self.tray.isChecked(),
            "convert_to_h264": self.convert.isChecked(),
            "check_ytdlp_updates": self.check_ytdlp.isChecked(),
        }
        try:
            for key, value in values.items():
                self.settings.set(key, value)
        except ValueError as e:
            QMessageBox.warning(self, "Opciones", str(e))
            return
        super().accept()
