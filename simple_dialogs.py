# simple_dialogs.py - Diálogos pequeños: añadir URL, eliminar descargas, cuenta regresiva y registro
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox,
    QPlainTextEdit, QFileDialog, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QTimer

import icons


class AddUrlDialog(QDialog):
    """'Introduce la dirección para descargar' (como IDM): toma la URL del portapapeles si hay una."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Añadir enlace")
        self.setWindowIcon(icons.icon("add"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Dirección del archivo, video o página:"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://")
        clipboard = QApplication.clipboard().text().strip()
        if clipboard.lower().startswith(("http://", "https://")) and "\n" not in clipboard:
            self.url_input.setText(clipboard)
            self.url_input.selectAll()
        layout.addWidget(self.url_input)
        hint = QLabel("Si es una página con video, Geas busca el video; si es un archivo, lo descarga.")
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch()
        ok_button = QPushButton("Aceptar")
        ok_button.setObjectName("PrimaryButton")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(ok_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    def url(self):
        return self.url_input.text().strip()


class DeleteDialog(QDialog):
    """Confirmación para quitar descargas de la lista, opcionalmente borrando los archivos."""

    def __init__(self, count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Eliminar descargas")
        self.setWindowIcon(icons.icon("delete"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icons.icon("delete").pixmap(36, 36))
        text = "¿Quitar esta descarga de la lista?" if count == 1 else f"¿Quitar estas {count} descargas de la lista?"
        header.addWidget(icon_label)
        header.addWidget(QLabel(text), 1)
        layout.addLayout(header)
        self.delete_files = QCheckBox("Borrar también los archivos del disco")
        layout.addWidget(self.delete_files)

        buttons = QHBoxLayout()
        buttons.addStretch()
        yes_button = QPushButton("Eliminar")
        yes_button.setDefault(True)
        yes_button.clicked.connect(self.accept)
        no_button = QPushButton("Cancelar")
        no_button.clicked.connect(self.reject)
        buttons.addWidget(yes_button)
        buttons.addWidget(no_button)
        layout.addLayout(buttons)


class CountdownDialog(QDialog):
    """
    Aviso antes de apagar, suspender o cerrar: se acepta solo al llegar a cero
    o con "Ahora"; "Cancelar" lo evita.
    """

    def __init__(self, text, seconds=30, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Descargas terminadas")
        self.setWindowIcon(icons.icon("finished"))
        self.setWindowFlags((self.windowFlags() & ~Qt.WindowContextHelpButtonHint) | Qt.WindowStaysOnTopHint)
        self._text = text  # "El equipo se apagará"
        self._remaining = seconds

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icons.icon("finished").pixmap(36, 36))
        self.label = QLabel()
        header.addWidget(icon_label)
        header.addWidget(self.label, 1)
        layout.addLayout(header)

        buttons = QHBoxLayout()
        buttons.addStretch()
        now_button = QPushButton("Ahora")
        now_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancelar")
        cancel_button.setDefault(True)  # Enter no apaga el equipo por error
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(now_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._show_remaining()

    def _show_remaining(self):
        self.label.setText(f"Todas las descargas terminaron.\n{self._text} en {self._remaining} s.")

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.accept()
        else:
            self._show_remaining()


class LogWindow(QDialog):
    """Registro de actividad (antes la pestaña Logs). Se crea al iniciar y solo se muestra cuando se pide."""

    MAX_LINES = 1000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actividad de Geas")
        self.setWindowIcon(icons.icon("log"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setObjectName("LogView")
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(self.MAX_LINES)
        self.text.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 9pt;")
        layout.addWidget(self.text)

        buttons = QHBoxLayout()
        clear_button = QPushButton("Limpiar")
        clear_button.clicked.connect(self.text.clear)
        save_button = QPushButton("Guardar…")
        save_button.clicked.connect(self.save)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.hide)
        buttons.addWidget(clear_button)
        buttons.addWidget(save_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def append(self, message):
        self.text.appendPlainText(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar registro",
                                              f"registro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                                              "Archivos de texto (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.text.toPlainText())
            except OSError as e:
                QMessageBox.warning(self, "Actividad", f"No se pudo guardar:\n{e}")
