# welcome_dialog.py - "Primeros pasos": conectar el navegador, ffmpeg y cómo descargar
import os
import subprocess

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QLineEdit, QProgressBar, QApplication,
    QComboBox, QWidget
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

import browsers
import icons
import paths
from media_handler import find_ffmpeg

EXTENSION_DIR = os.path.join(paths.APP_DIR, "extension")


def _hint(text):
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


class WelcomeDialog(QDialog):
    """Se abre la primera vez; después, desde Ayuda → Primeros pasos."""

    def __init__(self, extension_connected, ffmpeg_setup=None, parent=None, found_browsers=None):
        super().__init__(parent)
        self.extension_connected = extension_connected  # función: True si la extensión ya habló con Geas
        self.ffmpeg_setup = ffmpeg_setup                 # descarga de ffmpeg de la ventana principal
        self.browsers = browsers.installed() if found_browsers is None else found_browsers
        self.setWindowTitle("Bienvenido a Geas")
        self.setWindowIcon(icons.icon("app"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.icon("app").pixmap(48, 48))
        title = QLabel("Geas Download Manager\nPara empezar")
        title.setObjectName("DialogTitle")
        header.addWidget(logo)
        header.addWidget(title, 1)
        layout.addLayout(header)

        # --- 1. Navegador ---
        browser_box = QGroupBox("1. Conecta tu navegador")
        browser = QVBoxLayout(browser_box)
        self.extension_status = QLabel()
        browser.addWidget(self.extension_status)
        self.browser_combo = QComboBox()
        for item in self.browsers:
            self.browser_combo.addItem(item.name + (" (tu navegador predeterminado)" if item.default else ""))
        choose_row = QWidget()
        choose = QHBoxLayout(choose_row)
        choose.setContentsMargins(0, 0, 0, 0)
        choose.addWidget(QLabel("Tu navegador:"))
        choose.addWidget(self.browser_combo, 1)
        choose_row.setVisible(len(self.browsers) > 1)  # con un solo navegador no hay nada que elegir
        browser.addWidget(choose_row)
        self.steps_layout = QVBoxLayout()  # pasos del navegador elegido
        browser.addLayout(self.steps_layout)
        layout.addWidget(browser_box)
        self.browser_combo.currentIndexChanged.connect(self._show_steps)
        self._show_steps(0)

        # --- 2. ffmpeg ---
        ffmpeg_box = QGroupBox("2. ffmpeg: lo descarga Geas")
        ffmpeg = QVBoxLayout(ffmpeg_box)
        ffmpeg.addWidget(_hint("Une el video y el audio en alta calidad, convierte a H.264 e incrusta subtítulos. "
                               "Geas lo descarga sola, una única vez (unos 115 MB), de la compilación oficial "
                               "para Windows. Puedes seguir usando Geas mientras tanto."))
        ffmpeg_row = QHBoxLayout()
        self.ffmpeg_status = QLabel()
        self.ffmpeg_status.setWordWrap(True)
        self.ffmpeg_button = QPushButton(icons.icon("redownload"), "Reintentar")
        self.ffmpeg_button.clicked.connect(self._retry_ffmpeg)
        ffmpeg_row.addWidget(self.ffmpeg_status, 1)
        ffmpeg_row.addWidget(self.ffmpeg_button)
        ffmpeg.addLayout(ffmpeg_row)
        self.ffmpeg_bar = QProgressBar()
        self.ffmpeg_bar.setMaximumHeight(14)
        ffmpeg.addWidget(self.ffmpeg_bar)
        layout.addWidget(ffmpeg_box)

        # --- 3. Cómo descargar ---
        tips_box = QGroupBox("3. Cómo descargar")
        tips = QVBoxLayout(tips_box)
        tips_text = QLabel(
            "• Descarga como siempre en el navegador: Geas toma los archivos (zip, exe, pdf, mp4...).<br>"
            "• En una página con video, pulsa <b>Descargar video</b> sobre el reproductor.<br>"
            "• En Geas, <b>Ctrl+V</b> pega un enlace y lo descarga.<br>"
            "• Clic derecho en una página → <b>Descargar todos los enlaces con Geas</b>.<br>"
            "• <b>Tareas → Control desde el celular</b> para añadir descargas desde el teléfono.")
        tips_text.setWordWrap(True)
        tips.addWidget(tips_text)
        layout.addWidget(tips_box)

        buttons = QHBoxLayout()
        again = _hint("Puedes volver a abrir esta ventana desde Ayuda → Primeros pasos.")
        start = QPushButton("Empezar")
        start.setObjectName("PrimaryButton")
        start.setDefault(True)
        start.clicked.connect(self.accept)
        buttons.addWidget(again, 1)
        buttons.addWidget(start)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        if ffmpeg_setup is not None:
            ffmpeg_setup.changed.connect(self.refresh)
        self.refresh()

    # --- Navegador ---

    def _show_steps(self, index):
        """Pasos para el navegador elegido: tienda (un clic) o carpeta en modo de desarrollador."""
        self._clear(self.steps_layout)
        browser = self.browsers[index] if 0 <= index < len(self.browsers) else None
        add = self.steps_layout.addWidget
        QTimer.singleShot(0, self._fit_height)  # con los pasos nuevos ya en su lugar

        if browser and browser.store_url:
            add(QLabel("Pulsa el botón y, en la tienda, «Añadir» o «Obtener»:"))
            row = QHBoxLayout()
            button = QPushButton(icons.icon("browser"), f"Añadir Geas a {browser.name}")
            button.setObjectName("PrimaryButton")
            button.clicked.connect(lambda _=False, b=browser: self._launch(b, b.store_url))
            row.addWidget(button)
            row.addStretch()
            self.steps_layout.addLayout(row)
        elif browser and not browser.chromium:
            add(_hint("Firefox solo instala extensiones firmadas por Mozilla: la de Geas llegará cuando se publique "
                      "en su tienda de complementos. Mientras tanto, copia el enlace de la descarga y pégalo en "
                      "Geas con Ctrl+V." + (" O conéctala con otro navegador de la lista." if len(self.browsers) > 1
                                            else "")))
        else:
            name = browser.name if browser else "tu navegador"
            row = QHBoxLayout()
            if browser:
                button = QPushButton(icons.icon("browser"), f"① Abrir las extensiones de {browser.name}")
                button.setToolTip("También copia la ruta de la carpeta de la extensión, para pegarla en el paso ③")
                button.clicked.connect(lambda _=False, b=browser: self._open_extensions(b))
                row.addWidget(button)
                row.addStretch()
                self.steps_layout.addLayout(row)
            else:
                add(QLabel("① Abre chrome://extensions (o edge://extensions) en tu navegador."))
            add(QLabel(f"② Activa el «Modo de desarrollador» "
                       f"({browser.developer_switch if browser else 'arriba a la derecha'})."))
            button_name = browser.load_button if browser else "Cargar descomprimida"
            add(QLabel(f"③ Pulsa «{button_name}», pega la ruta con Ctrl+V y pulsa «Seleccionar carpeta»."))
            folder_row = QHBoxLayout()
            folder = QLineEdit(EXTENSION_DIR)
            folder.setReadOnly(True)
            folder.setCursorPosition(0)
            open_folder = QPushButton(icons.icon("folder"), "Abrir la carpeta")
            open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(EXTENSION_DIR)))
            copy_path = QPushButton("Copiar la ruta")
            copy_path.clicked.connect(lambda: QApplication.clipboard().setText(EXTENSION_DIR))
            folder_row.addWidget(folder, 1)
            folder_row.addWidget(open_folder)
            folder_row.addWidget(copy_path)
            self.steps_layout.addLayout(folder_row)
            add(_hint(f"Después, pulsa el ícono de Geas en la barra de {name}: aquí arriba se verá «conectada»."))

    def _fit_height(self):
        # Qt no cuenta los textos que se parten en varias líneas al calcular el alto mínimo de la ventana
        needed = self.layout().totalHeightForWidth(self.width())
        self.setMinimumHeight(needed)
        if self.height() < needed:
            self.resize(self.width(), needed)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_height()

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)  # fuera de la vista ya, no en el próximo ciclo
                widget.deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def _open_extensions(self, browser):
        QApplication.clipboard().setText(EXTENSION_DIR)  # para pegarla en «Cargar descomprimida»
        self._launch(browser, browser.extensions_page)

    @staticmethod
    def _launch(browser, url):
        # chrome://, edge://... solo se abren pasándolos al ejecutable del navegador
        subprocess.Popen([browser.exe, url])

    # --- Estado ---

    def refresh(self):
        if self.extension_connected():
            self.extension_status.setText("✓ La extensión está conectada.")
            self.extension_status.setObjectName("FieldName")
        else:
            self.extension_status.setText("La extensión todavía no se conectó con Geas.")
            self.extension_status.setObjectName("Warning")
        self.extension_status.style().unpolish(self.extension_status)
        self.extension_status.style().polish(self.extension_status)

        setup = self.ffmpeg_setup
        busy = setup is not None and setup.busy
        self.ffmpeg_bar.setVisible(busy)
        self.ffmpeg_button.setVisible(False)
        if busy:
            percent = setup.percent()
            if percent is None:
                self.ffmpeg_bar.setRange(0, 0)
                self.ffmpeg_status.setText("Descargando ffmpeg…")
            else:
                self.ffmpeg_bar.setRange(0, 100)
                self.ffmpeg_bar.setValue(percent)
                self.ffmpeg_status.setText("Preparando ffmpeg…" if percent >= 100 else
                                           f"Descargando ffmpeg… {percent} %")
        elif find_ffmpeg():
            self.ffmpeg_status.setText("✓ ffmpeg está listo.")
        elif setup is not None and setup.error:
            self.ffmpeg_status.setText(f"No se pudo descargar ffmpeg: {setup.error}.")
            self.ffmpeg_button.setVisible(True)
        else:
            self.ffmpeg_status.setText("ffmpeg todavía no está.")
            self.ffmpeg_button.setVisible(setup is not None)
        if self.isVisible():
            self._fit_height()  # la barra de avance aparece o se va

    def _retry_ffmpeg(self):
        self.ffmpeg_setup.ensure()
        self.refresh()
