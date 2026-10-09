# refresh_dialog.py - "Actualizar dirección de descarga" (como en IDM): enlace nuevo para una descarga a medias
import os

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

import icons
from file_info_dialog import UrlProbeThread
from ui_format import format_size

_running_probes = set()  # consultas en curso: Qt no debe destruirlas antes de que terminen


class RefreshAddressDialog(QDialog):
    """
    Los enlaces de muchos servidores vencen: con uno nuevo, la descarga sigue
    desde donde quedó. El enlace se pega aquí o llega solo al volver a hacer
    clic en él en el navegador (con la sesión del navegador).
    """

    def __init__(self, entry, expected_size=0, referer=None, parent=None):
        super().__init__(parent)
        self.expected_size = int(expected_size or 0)
        self.referer = referer
        self.headers = None  # cabeceras y cookies del navegador, si el enlace vino de él
        self.cookies = None
        self._last_probed = None
        self.setWindowTitle("Actualizar dirección de descarga")
        self.setWindowIcon(icons.icon("redownload"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel("Archivo:"), 0, 0)
        grid.addWidget(QLabel(os.path.basename(entry.get("output_path", "")) or "—"), 0, 1)
        grid.addWidget(QLabel("Dirección actual:"), 1, 0)
        current = QLineEdit(entry.get("url", ""))
        current.setReadOnly(True)
        current.setCursorPosition(0)
        grid.addWidget(current, 1, 1)
        grid.addWidget(QLabel("Dirección nueva:"), 2, 0)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://")
        self.url_input.textEdited.connect(self._on_edited)
        grid.addWidget(self.url_input, 2, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        hint = QLabel("Vuelve a hacer clic en el enlace de descarga en el navegador: Geas tomará la dirección "
                      "nueva con tu sesión. También puedes pegarla aquí.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        buttons = QHBoxLayout()
        if referer:
            page_button = QPushButton(icons.icon("browser"), "Abrir la página de descarga")
            page_button.setToolTip(referer)
            page_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(referer)))
            buttons.addWidget(page_button)
        buttons.addStretch()
        self.ok_button = QPushButton("Continuar la descarga")
        self.ok_button.setObjectName("PrimaryButton")
        self.ok_button.setDefault(True)
        self.ok_button.setEnabled(False)
        self.ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self._probe_timer = QTimer(self)  # consulta el enlace cuando se deja de escribir
        self._probe_timer.setSingleShot(True)
        self._probe_timer.timeout.connect(self._probe)

    def url(self):
        return self.url_input.text().strip()

    def capture(self, url, context):
        """Enlace que llegó del navegador mientras la ventana está abierta."""
        self.headers, self.cookies = context.http_headers(), context.cookie_jar()
        self.url_input.setText(url)
        self.url_input.setCursorPosition(0)
        self._probe()
        self.raise_()
        self.activateWindow()

    def _on_edited(self):
        self.headers = self.cookies = None  # pegado a mano: sin la sesión del navegador
        self.ok_button.setEnabled(self.url().lower().startswith(("http://", "https://")))
        self._probe_timer.start(700)

    def _probe(self):
        url = self.url()
        if not url.lower().startswith(("http://", "https://")) or url == self._last_probed:
            return
        self._last_probed = url
        self.ok_button.setEnabled(True)
        self.result_label.setText("Comprobando el enlace…")
        thread = UrlProbeThread(url, self.headers, self.cookies)
        _running_probes.add(thread)
        thread.finished.connect(lambda: _running_probes.discard(thread))
        thread.probed.connect(lambda result, probed_url=url: self._on_probed(probed_url, result))
        thread.start()

    def _on_probed(self, url, result):
        if url != self.url():
            return  # llegó tarde: el enlace ya cambió
        size = int(result.get("size") or 0)
        if not result.get("ok"):
            text = f"No se pudo acceder al enlace: {result.get('error')}"
        elif not self.expected_size or not size:
            text = "El servidor no informa el tamaño: no se puede confirmar que sea el mismo archivo."
        elif size == self.expected_size:
            text = f"✓ Es el mismo archivo ({format_size(size)}): la descarga sigue desde donde quedó."
        else:
            text = (f"Este enlace es de otro archivo ({format_size(size)}; se esperaban "
                    f"{format_size(self.expected_size)}): se descargará desde el principio.")
        self.result_label.setText(text)
