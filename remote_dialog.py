# remote_dialog.py - "Control desde el celular": activar, código QR y cambio del código secreto
import qrcode
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QLineEdit
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap

import icons
from remote_server import local_ip


def qr_pixmap(text, size=240):
    """Código QR dibujado con Qt (negro sobre blanco aunque el tema sea oscuro: así lo leen las cámaras)."""
    code = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(text)
    code.make(fit=True)
    matrix = code.get_matrix()
    cell = max(1, size // len(matrix))
    pixmap = QPixmap(cell * len(matrix), cell * len(matrix))
    pixmap.fill(QColor("white"))
    painter = QPainter(pixmap)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                painter.fillRect(x * cell, y * cell, cell, cell, QColor("black"))
    painter.end()
    return pixmap


class RemoteDialog(QDialog):
    """Muestra cómo entrar desde el celular. Los cambios los aplica Geas (señales)."""
    enabled_changed = Signal(bool)
    new_code_requested = Signal()

    def __init__(self, enabled, port, token, error="", parent=None):
        super().__init__(parent)
        self.port = port
        self.setWindowTitle("Control desde el celular")
        self.setWindowIcon(icons.icon("app"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("Permitir el control desde el celular")
        self.enabled.setChecked(enabled)
        self.enabled.toggled.connect(self.enabled_changed.emit)
        layout.addWidget(self.enabled)
        intro = QLabel("Desde el navegador del celular podrás añadir enlaces y ver, pausar o cancelar las "
                       "descargas. El celular tiene que estar en la misma red Wi-Fi que esta PC.")
        intro.setObjectName("Hint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.qr)
        self.instructions = QLabel()
        self.instructions.setWordWrap(True)
        self.instructions.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.instructions)
        self.address = QLineEdit()
        self.address.setReadOnly(True)
        layout.addWidget(self.address)

        warning = QLabel("Quien tenga este código y esté en tu red puede añadir descargas en esta PC. Úsalo en "
                         "redes de confianza (tu casa). Si Windows pregunta, permite el acceso en redes privadas.")
        warning.setObjectName("Warning")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QHBoxLayout()
        self.new_code = QPushButton("Cambiar el código")
        self.new_code.setToolTip("Los celulares que ya entraron tendrán que escanear el código nuevo")
        self.new_code.clicked.connect(self.new_code_requested.emit)
        close = QPushButton("Cerrar")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(self.new_code)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.show_state(enabled, token, error)

    def show_state(self, running, token, error=""):
        """Actualiza la ventana: activo (QR y dirección), apagado o con error."""
        ip = local_ip()
        active = running and bool(ip) and not error
        self.qr.setVisible(active)
        self.address.setVisible(active)
        self.new_code.setEnabled(active)
        if error:
            self.instructions.setText(f"No se pudo activar: {error}")
        elif running and not ip:
            self.instructions.setText("Esta PC no está conectada a una red: conéctala a tu Wi-Fi o por cable.")
        elif not running:
            self.instructions.setText("Desactivado: Geas no acepta conexiones desde la red.")
        else:
            url = f"http://{ip}:{self.port}/?t={token}"
            self.qr.setPixmap(qr_pixmap(url))
            self.address.setText(url)
            self.instructions.setText("Escanea el código con la cámara del celular y abre el enlace. "
                                      "Después puedes guardarlo en la pantalla de inicio.")
