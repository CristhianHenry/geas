# options_dialog.py - Opciones de Geas (pestañas como en IDM)
import os
from urllib.parse import urlparse

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget, QCheckBox,
    QSpinBox, QLineEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QDialogButtonBox,
    QGroupBox, QRadioButton, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox
)
from PySide6.QtCore import Qt

import app_updater
import icons
import network
import secure_store
import theme
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
        tabs.addTab(self._proxy_tab(), "Proxy y sitios")
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
        self.check_app = self._check("Buscar una versión nueva de Geas una vez al día", "check_app_updates")
        self.check_app.setVisible(app_updater.enabled())  # solo la versión instalada se actualiza sola
        for widget in (self.auto_start, self.show_progress, self.clipboard, self.notifications, self.tray,
                       self.check_app):
            layout.addWidget(widget)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Tema:"))
        self.theme = QComboBox()
        for value, label in theme.CHOICES:
            self.theme.addItem(label, value)
        self.theme.setCurrentIndex(max(0, self.theme.findData(self.settings.get("theme"))))
        theme_row.addWidget(self.theme)
        theme_row.addStretch()
        layout.addSpacing(6)
        layout.addLayout(theme_row)
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

    def _proxy_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        proxy_box = QGroupBox("Proxy")
        proxy_layout = QVBoxLayout(proxy_box)
        self.proxy_system = QRadioButton("Usar el proxy de Windows (recomendado)")
        self.proxy_none = QRadioButton("Conectar directo, sin proxy")
        self.proxy_manual = QRadioButton("Usar este proxy:")
        self.proxy_url = QLineEdit(secure_store.unprotect(self.settings.get("proxy_url")) or "")
        self.proxy_url.setPlaceholderText("http://servidor:puerto   o   socks5://servidor:puerto")
        mode = self.settings.get("proxy_mode")
        {network.PROXY_NONE: self.proxy_none, network.PROXY_MANUAL: self.proxy_manual}.get(
            mode, self.proxy_system).setChecked(True)
        self.proxy_url.setEnabled(self.proxy_manual.isChecked())
        self.proxy_manual.toggled.connect(self.proxy_url.setEnabled)
        manual_row = QHBoxLayout()
        manual_row.addWidget(self.proxy_manual)
        manual_row.addWidget(self.proxy_url, 1)
        proxy_hint = QLabel("Con usuario: http://usuario:contraseña@servidor:puerto. Vale para las descargas, "
                            "los videos y la comprobación de versiones.")
        proxy_hint.setObjectName("Hint")
        proxy_hint.setWordWrap(True)
        for widget in (self.proxy_system, self.proxy_none):
            proxy_layout.addWidget(widget)
        proxy_layout.addLayout(manual_row)
        proxy_layout.addWidget(proxy_hint)
        layout.addWidget(proxy_box)

        logins_box = QGroupBox("Usuarios por sitio")
        logins_layout = QVBoxLayout(logins_box)
        self.logins = [{"site": item.get("site", ""), "user": item.get("user", ""),
                        "password": secure_store.unprotect(item.get("password")) or ""}
                       for item in self.settings.get("site_logins") or []]
        self.logins_table = QTableWidget(0, 3)
        self.logins_table.setHorizontalHeaderLabels(["Sitio", "Usuario", "Contraseña"])
        self.logins_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.logins_table.verticalHeader().setVisible(False)
        self.logins_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.logins_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.logins_table.setMinimumHeight(110)
        self._fill_logins()
        logins_layout.addWidget(self.logins_table)
        row = QHBoxLayout()
        add_button = QPushButton("Añadir…")
        add_button.clicked.connect(self.add_login)
        remove_button = QPushButton("Quitar")
        remove_button.clicked.connect(self.remove_login)
        row.addWidget(add_button)
        row.addWidget(remove_button)
        row.addStretch()
        logins_layout.addLayout(row)
        logins_hint = QLabel("Geas los usa cuando el servidor de una descarga pide usuario y contraseña "
                             "(autenticación HTTP básica); valen también para los subdominios. Se guardan "
                             "cifrados con tu usuario de Windows.")
        logins_hint.setObjectName("Hint")
        logins_hint.setWordWrap(True)
        logins_layout.addWidget(logins_hint)
        layout.addWidget(logins_box)
        return page

    def _fill_logins(self):
        self.logins_table.setRowCount(len(self.logins))
        for row, login in enumerate(self.logins):
            for column, text in enumerate((login["site"], login["user"], "•" * 8 if login["password"] else "")):
                self.logins_table.setItem(row, column, QTableWidgetItem(text))

    def add_login(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Usuario para un sitio")
        dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        form = QFormLayout(dialog)
        site, user, password = QLineEdit(), QLineEdit(), QLineEdit()
        site.setPlaceholderText("ejemplo.com")
        password.setEchoMode(QLineEdit.Password)
        form.addRow("Sitio:", site)
        form.addRow("Usuario:", user)
        form.addRow("Contraseña:", password)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Aceptar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        text = site.text().strip()
        host = (urlparse(text if "://" in text else "http://" + text).hostname or "").lower()  # admite una URL
        if not host or not user.text().strip():
            QMessageBox.warning(self, "Opciones", "Escribe el sitio y el usuario.")
            return
        self.logins = [login for login in self.logins if login["site"] != host]
        self.logins.append({"site": host, "user": user.text().strip(), "password": password.text()})
        self._fill_logins()

    def remove_login(self):
        rows = sorted({index.row() for index in self.logins_table.selectedIndexes()}, reverse=True)
        for row in rows:
            del self.logins[row]
        self._fill_logins()

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
        layout.addSpacing(8)
        self.category_folders = self._check("Guardar cada tipo de archivo en su subcarpeta", "category_folders")
        layout.addWidget(self.category_folders)
        example = QLabel("Video, Música, Comprimidos, Documentos y Programas, dentro de la carpeta de arriba "
                         "(por ejemplo: Descargas\\Video\\capitulo.mp4). Los demás archivos quedan en la carpeta.")
        example.setObjectName("Hint")
        example.setWordWrap(True)
        layout.addWidget(example)
        layout.addStretch()
        return page

    def _video_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.convert = self._check("Convertir a H.264 los videos en AV1, VP9 o HEVC al terminar", "convert_to_h264",
                                   "El Reproductor de Windows, las teles y los móviles abren H.264 sin códecs extra")
        layout.addWidget(self.convert)
        self.hardware = self._check("Usar la tarjeta gráfica para convertir (mucho más rápido)",
                                    "hardware_encoding",
                                    "NVIDIA, Intel Quick Sync o AMD. Si no hay o falla, se usa el procesador")
        self.hardware.setEnabled(self.convert.isChecked())
        self.convert.toggled.connect(self.hardware.setEnabled)
        layout.addWidget(self.hardware)
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
            status = QLabel("ffmpeg todavía no está: Geas lo descarga sola (el avance se ve abajo a la derecha). "
                            "Sin él los videos no se reempaquetan ni se convierten.")
            status.setObjectName("Warning")
            status.setWordWrap(True)
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
            "category_folders": self.category_folders.isChecked(),
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
            "hardware_encoding": self.hardware.isChecked(),
            "check_ytdlp_updates": self.check_ytdlp.isChecked(),
            "check_app_updates": self.check_app.isChecked(),
            "theme": self.theme.currentData(),
            "proxy_mode": (network.PROXY_MANUAL if self.proxy_manual.isChecked()
                           else network.PROXY_NONE if self.proxy_none.isChecked() else network.PROXY_SYSTEM),
            "proxy_url": secure_store.protect(network.normalize_proxy(self.proxy_url.text())) or "",
            "site_logins": [{"site": login["site"], "user": login["user"],
                             "password": secure_store.protect(login["password"]) or ""} for login in self.logins],
        }
        if values["proxy_mode"] == network.PROXY_MANUAL and not self.proxy_url.text().strip():
            QMessageBox.warning(self, "Opciones", "Escribe la dirección del proxy o elige otra opción.")
            return
        try:
            for key, value in values.items():
                self.settings.set(key, value)
        except ValueError as e:
            QMessageBox.warning(self, "Opciones", str(e))
            return
        super().accept()
