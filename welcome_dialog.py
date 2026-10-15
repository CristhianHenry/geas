# welcome_dialog.py - "Primeros pasos": conectar el navegador, instalar ffmpeg y cómo descargar
import os
import shutil
import subprocess
import sys

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QLineEdit, QProgressBar, QApplication
)
from PySide6.QtCore import Qt, QTimer, QProcess, QUrl
from PySide6.QtGui import QDesktopServices

import icons
import paths
from media_handler import find_ffmpeg

EXTENSION_DIR = os.path.join(paths.APP_DIR, "extension")
FFMPEG_PAGE = "https://www.gyan.dev/ffmpeg/builds/"
# (navegador, ejecutable, página de extensiones)
BROWSERS = [("Chrome", "chrome.exe", "chrome://extensions/"), ("Edge", "msedge.exe", "edge://extensions/")]


def browser_exe(name):
    """Ruta del navegador según Windows (App Paths), o None si no está instalado."""
    if sys.platform != "win32":
        return None
    import winreg
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + name
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key_path) as key:
                path = winreg.QueryValue(key, None)
            if path and os.path.isfile(path.strip('"')):
                return path.strip('"')
        except OSError:
            continue
    return None


class WelcomeDialog(QDialog):
    """Se abre la primera vez; después, desde Ayuda → Primeros pasos."""

    def __init__(self, extension_connected, parent=None):
        super().__init__(parent)
        self.extension_connected = extension_connected  # función: True si la extensión ya habló con Geas
        self.installer = None
        self.setWindowTitle("Bienvenido a Geas")
        self.setWindowIcon(icons.icon("app"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.icon("app").pixmap(48, 48))
        title = QLabel("Geas Download Manager\nTres pasos para empezar")
        title.setObjectName("DialogTitle")
        header.addWidget(logo)
        header.addWidget(title, 1)
        layout.addLayout(header)

        # --- 1. Navegador ---
        browser_box = QGroupBox("1. Conecta tu navegador")
        browser = QVBoxLayout(browser_box)
        self.extension_status = QLabel()
        browser.addWidget(self.extension_status)
        browser.addWidget(QLabel("① Abre la página de extensiones de tu navegador:"))
        open_row = QHBoxLayout()
        for name, exe, page in BROWSERS:
            path = browser_exe(exe)
            if path:
                button = QPushButton(icons.icon("browser"), f"Extensiones de {name}")
                button.clicked.connect(lambda _=False, p=path, u=page: subprocess.Popen([p, u]))
                open_row.addWidget(button)
        open_row.addStretch()
        browser.addLayout(open_row)
        browser.addWidget(QLabel("② Activa el «Modo de desarrollador» (arriba a la derecha)."))
        browser.addWidget(QLabel("③ Pulsa «Cargar extensión sin empaquetar» (o «descomprimida») y elige esta carpeta:"))
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
        browser.addLayout(folder_row)
        then = QLabel("Después, abre el ícono de Geas en la barra del navegador: aquí se verá «conectada».")
        then.setObjectName("Hint")
        then.setWordWrap(True)
        browser.addWidget(then)
        layout.addWidget(browser_box)

        # --- 2. ffmpeg ---
        ffmpeg_box = QGroupBox("2. Instala ffmpeg (recomendado)")
        ffmpeg = QVBoxLayout(ffmpeg_box)
        why = QLabel("Geas lo usa para unir el video y el audio en alta calidad, convertir a H.264 e incrustar "
                     "subtítulos. Se instala gratis con winget, desde el repositorio oficial de Microsoft.")
        why.setObjectName("Hint")
        why.setWordWrap(True)
        ffmpeg.addWidget(why)
        ffmpeg_row = QHBoxLayout()
        self.ffmpeg_status = QLabel()
        self.ffmpeg_button = QPushButton(icons.icon("redownload"), "Instalar ffmpeg")
        self.ffmpeg_button.clicked.connect(self.install_ffmpeg)
        ffmpeg_row.addWidget(self.ffmpeg_status, 1)
        ffmpeg_row.addWidget(self.ffmpeg_button)
        ffmpeg.addLayout(ffmpeg_row)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setMaximumHeight(10)
        self.busy.hide()
        ffmpeg.addWidget(self.busy)
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
        again = QLabel("Puedes volver a abrir esta ventana desde Ayuda → Primeros pasos.")
        again.setObjectName("Hint")
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
        self.refresh()

    def refresh(self):
        if self.extension_connected():
            self.extension_status.setText("✓ La extensión está conectada.")
            self.extension_status.setObjectName("FieldName")
        else:
            self.extension_status.setText("La extensión todavía no se conectó con Geas.")
            self.extension_status.setObjectName("Warning")
        self.extension_status.style().unpolish(self.extension_status)
        self.extension_status.style().polish(self.extension_status)
        if self.installer is not None:
            return  # instalando: el estado lo actualiza install_finished
        if find_ffmpeg():
            self.ffmpeg_status.setText("✓ ffmpeg está instalado.")
            self.ffmpeg_button.hide()
        else:
            self.ffmpeg_status.setText("ffmpeg no está instalado.")
            self.ffmpeg_button.show()

    def install_ffmpeg(self):
        if not shutil.which("winget"):
            # Windows sin winget (algunos Windows 10): se descarga a mano
            QDesktopServices.openUrl(QUrl(FFMPEG_PAGE))
            self.ffmpeg_status.setText("Este Windows no tiene winget: se abrió la página de descarga de ffmpeg.")
            return
        self.ffmpeg_button.setEnabled(False)
        self.busy.show()
        self.ffmpeg_status.setText("Instalando ffmpeg… (puede tardar un par de minutos)")
        self.installer = QProcess(self)
        self.installer.finished.connect(self.install_finished)
        self.installer.start("winget", ["install", "--id", "Gyan.FFmpeg.Essentials", "-e",
                                        "--accept-package-agreements", "--accept-source-agreements",
                                        "--disable-interactivity"])

    def install_finished(self, exit_code, _status):
        self.installer = None
        self.busy.hide()
        self.ffmpeg_button.setEnabled(True)
        if find_ffmpeg():
            self.ffmpeg_status.setText("✓ ffmpeg quedó instalado.")
            self.ffmpeg_button.hide()
        else:
            self.ffmpeg_status.setText(f"No se pudo instalar ffmpeg (código {exit_code}). Puedes descargarlo "
                                       f"de {FFMPEG_PAGE}")

    def done(self, result):
        if self.installer is not None:
            # Cortar winget a medias dejaría ffmpeg mal instalado: se espera a que termine
            self.ffmpeg_status.setText("Espera a que termine la instalación de ffmpeg…")
            return
        super().done(result)
