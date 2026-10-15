# file_info_dialog.py - Diálogo "Información del archivo" (como el de IDM)

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog
)
from PySide6.QtCore import QThread, Signal, Qt

import icons
from enhanced_downloader import sanitize_filename, unique_path, url_probe
from file_categories import category_of
from ui_format import format_size


class UrlProbeThread(QThread):
    """Consulta una URL (tipo, tamaño y nombre) sin congelar la interfaz"""
    probed = Signal(object)  # dict de url_probe()

    def __init__(self, url, headers=None, cookies=None):
        super().__init__()
        self.url = url
        self.headers = headers
        self.cookies = cookies

    def run(self):
        self.probed.emit(url_probe(self.url, self.headers, self.cookies))


class FileInfoDialog(QDialog):
    """URL, ruta de destino y tamaño antes de iniciar (o dejar para más tarde) una descarga."""

    def __init__(self, url, save_path, size=None, parent=None):
        super().__init__(parent)
        self.start_now = True
        self.setWindowTitle("Información del archivo")
        self.setWindowIcon(icons.icon("app"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(600)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icons.icon(category_of(save_path)[1]).pixmap(40, 40))
        title = QLabel(os.path.basename(save_path))
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        header.addWidget(icon_label)
        header.addWidget(title, 1)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        url_field = QLineEdit(url)
        url_field.setReadOnly(True)
        url_field.setCursorPosition(0)
        grid.addWidget(QLabel("Enlace:"), 0, 0)
        grid.addWidget(url_field, 0, 1, 1, 2)

        self.path_input = QLineEdit(save_path)
        browse_button = QPushButton("…")
        browse_button.setObjectName("BrowseButton")
        browse_button.setToolTip("Elegir dónde guardar")
        browse_button.clicked.connect(self.browse)
        grid.addWidget(QLabel("Guardar como:"), 1, 0)
        grid.addWidget(self.path_input, 1, 1)
        grid.addWidget(browse_button, 1, 2)

        grid.addWidget(QLabel("Tamaño:"), 2, 0)
        grid.addWidget(QLabel(format_size(size) or "Desconocido"), 2, 1)
        layout.addLayout(grid)

        buttons = QHBoxLayout()
        buttons.addStretch()
        start_button = QPushButton(icons.icon("resume"), "Iniciar descarga")
        start_button.setObjectName("PrimaryButton")
        start_button.setDefault(True)
        start_button.clicked.connect(self.accept)
        later_button = QPushButton("Descargar más tarde")
        later_button.clicked.connect(self.download_later)
        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(start_button)
        buttons.addWidget(later_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    def browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar como", self.path_input.text(), "Todos los archivos (*.*)")
        if path:
            self.path_input.setText(os.path.normpath(path))

    def download_later(self):
        self.start_now = False
        self.accept()

    def save_path(self):
        """Ruta final (sin pisar archivos existentes)"""
        path = self.path_input.text().strip()
        folder = os.path.dirname(path) or os.path.expanduser("~/Downloads")
        return unique_path(os.path.join(folder, sanitize_filename(os.path.basename(path))))
