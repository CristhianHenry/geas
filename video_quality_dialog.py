import os
from urllib.parse import urlparse

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QProgressBar,
    QGroupBox, QCheckBox, QFileDialog, QAbstractItemView
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
import requests

import icons
from enhanced_downloader import unique_path
from media_handler import MediaHandler
from ui_format import format_size


def safe_title(title):
    """Título apto como nombre de archivo (letras, números y ' .-_()')."""
    cleaned = "".join(c for c in (title or "") if c.isalpha() or c.isdigit() or c in " .-_()").strip(" .")
    return cleaned or "video"


class MediaInfoThread(QThread):
    """Hilo para obtener información del medio sin congelar la UI"""
    info_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, url, context=None, prefer_stream=False):
        super().__init__()
        self.url = url
        self.context = context
        self.prefer_stream = prefer_stream
        self.handler = MediaHandler()

    def run(self):
        info, errors = self.handler.resolve(self.url, self.context, self.prefer_stream)
        if not info:
            message = "No se encontró ningún video descargable en esta página."
            if errors:
                message += "\n\nDetalles:\n" + "\n".join(f"• {e[:200]}" for e in errors[-3:])
            message += ("\n\nSi el sitio cambió hace poco, puede que haga falta una versión nueva de yt-dlp: "
                        "Ayuda → Actualizar yt-dlp.")
            self.error_occurred.emit(message)
            return

        # La miniatura se descarga aquí para no bloquear la interfaz
        thumbnail_url = info.get('thumbnail')
        if thumbnail_url:
            try:
                info['_thumbnail_data'] = requests.get(thumbnail_url, timeout=5).content
            except requests.RequestException:
                pass
        self.info_ready.emit(info)


class VideoQualityDialog(QDialog):
    def __init__(self, url, manager, parent=None, context=None, prefer_stream=False, folder=None,
                 convert_note=False, audio_folder=None):
        super().__init__(parent)
        self.url = url
        self.manager = manager
        self.context = context  # BrowserContext cuando la solicitud viene del navegador
        self.prefer_stream = prefer_stream
        self.folder = folder or os.path.expanduser("~/Downloads")
        self.audio_folder = audio_folder or self.folder  # "solo audio" (con carpetas por tipo: Música)
        self.convert_note = convert_note  # avisar que se convertirá a H.264 si hace falta
        self.media_handler = MediaHandler()
        self.selected_format = None
        self.selected_type = 'video'
        self.video_info = None
        self.video_title = None
        self.start_now = True
        self.smart_formats = []
        self.raw_formats = []

        self.setWindowTitle("Analizando video…")
        self.setWindowIcon(icons.icon("app"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(720, 520)

        self.setup_ui()
        self.start_analysis()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # === Cabecera (miniatura, título, duración y origen) ===
        header_layout = QHBoxLayout()
        self.thumb_label = QLabel("Cargando…")
        self.thumb_label.setFixedSize(160, 90)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #1b1b1b; color: #dddddd; border: 1px solid #9a9a9a;")

        info_layout = QVBoxLayout()
        self.title_label = QLabel("Analizando la página…")
        self.title_label.setObjectName("DialogTitle")
        self.title_label.setWordWrap(True)
        self.duration_label = QLabel("")
        self.source_label = QLabel("")
        self.source_label.setObjectName("Hint")
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)  # animación mientras se analiza
        self.busy_bar.setMaximumHeight(14)
        self.busy_bar.setTextVisible(False)
        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.duration_label)
        info_layout.addWidget(self.source_label)
        info_layout.addWidget(self.busy_bar)
        info_layout.addStretch()
        header_layout.addWidget(self.thumb_label)
        header_layout.addLayout(info_layout, 1)
        layout.addLayout(header_layout)

        # === Selector de formato ===
        self.format_group = QGroupBox("Calidad")
        format_layout = QVBoxLayout(self.format_group)
        self.format_table = QTableWidget(0, 5)
        self.format_table.setHorizontalHeaderLabels(["Calidad", "Formato", "Tamaño", "Códec", "ID"])
        self.format_table.setColumnHidden(4, True)
        self.format_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.format_table.verticalHeader().setVisible(False)
        self.format_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.format_table.setSelectionMode(QTableWidget.SingleSelection)
        self.format_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.format_table.setAlternatingRowColors(True)
        self.format_table.itemSelectionChanged.connect(self.on_selection_changed)
        self.format_table.itemDoubleClicked.connect(lambda _: self.start_download())
        self.advanced_view_cb = QCheckBox("Mostrar todos los formatos (avanzado)")
        self.advanced_view_cb.stateChanged.connect(self.toggle_advanced_view)
        format_layout.addWidget(self.format_table)
        format_layout.addWidget(self.advanced_view_cb)
        layout.addWidget(self.format_group, 1)

        # === Destino ===
        path_layout = QGridLayout()
        path_layout.setColumnStretch(1, 1)
        self.path_input = QLineEdit(os.path.join(self.folder, "video.mp4"))
        browse_button = QPushButton("…")
        browse_button.setObjectName("BrowseButton")
        browse_button.setToolTip("Elegir dónde guardar")
        browse_button.clicked.connect(self.browse)
        path_layout.addWidget(QLabel("Guardar como:"), 0, 0)
        path_layout.addWidget(self.path_input, 0, 1)
        path_layout.addWidget(browse_button, 0, 2)
        layout.addLayout(path_layout)

        self.note_label = QLabel("Si el video viene en AV1, VP9 o HEVC, se convertirá a H.264 al terminar "
                                 "para que lo abra cualquier reproductor.")
        self.note_label.setObjectName("Hint")
        self.note_label.setWordWrap(True)
        self.note_label.setVisible(self.convert_note)
        layout.addWidget(self.note_label)

        # === Botones ===
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.download_btn = QPushButton(icons.icon("resume"), "Descargar")
        self.download_btn.setObjectName("PrimaryButton")
        self.download_btn.setEnabled(False)
        self.download_btn.setDefault(True)
        self.download_btn.clicked.connect(self.start_download)
        self.later_btn = QPushButton("Descargar más tarde")
        self.later_btn.setEnabled(False)
        self.later_btn.clicked.connect(self.download_later)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.download_btn)
        btn_layout.addWidget(self.later_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def start_analysis(self):
        self.thread = MediaInfoThread(self.url, self.context, self.prefer_stream)
        self.thread.info_ready.connect(self.on_info_ready)
        self.thread.error_occurred.connect(self.on_error)
        self.thread.start()

    def on_info_ready(self, info):
        if not self.isVisible():
            return  # el usuario cerró el diálogo durante el análisis
        self.video_info = info
        self.setWindowTitle("Descargar video")
        self.busy_bar.hide()

        # Un stream directo (m3u8, mpd, mp4) no trae título útil: usar el de la pestaña
        title = info.get('title') or 'Video desconocido'
        source = info.get('_geas_source') or {}
        if source.get('is_stream') and self.context and self.context.title:
            title = self.context.title
        self.video_title = title
        self.title_label.setText(title)

        duration = info.get('duration')
        if duration:
            mins, secs = divmod(int(duration), 60)
            hours, mins = divmod(mins, 60)
            self.duration_label.setText(f"Duración: {hours}:{mins:02d}:{secs:02d}" if hours
                                        else f"Duración: {mins}:{secs:02d}")
        host = urlparse(source.get('url') or self.url).netloc
        kind = "stream detectado en la página" if source.get('is_stream') else "página"
        self.source_label.setText(f"Origen: {host} ({kind})")

        # Mostrar thumbnail (descargada por MediaInfoThread)
        thumbnail_data = info.get('_thumbnail_data')
        pixmap = QPixmap()
        if thumbnail_data and pixmap.loadFromData(thumbnail_data):
            self.thumb_label.setPixmap(pixmap.scaled(160, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb_label.setText("Sin vista previa")

        # Obtener ambas listas de formatos
        self.smart_formats = self.media_handler.get_formats(info)
        self.raw_formats = self.media_handler.get_raw_formats(info)
        self.populate_table()

    def populate_table(self):
        self.format_table.setRowCount(0)
        advanced = self.advanced_view_cb.isChecked()
        formats_to_show = self.raw_formats if advanced else self.smart_formats
        self.format_group.setTitle("Todos los formatos disponibles" if advanced else "Calidad")

        for f in formats_to_show:
            # En la vista avanzada se ocultan los videos sin resolución conocida
            if advanced and f['type'] == 'video' and f['resolution'] == 'N/A':
                continue
            size = f.get('filesize') or f.get('filesize_approx')
            self.add_row(f['resolution'], f['ext'], format_size(size) or "Desconocido",
                         f['vcodec'] or 'audio', f['format_id'], f['type'])
        if self.format_table.rowCount():
            self.format_table.selectRow(0)  # la mejor calidad, preseleccionada

    def add_row(self, quality, fmt, size, codec, fmt_id, fmt_type='video'):
        row = self.format_table.rowCount()
        self.format_table.insertRow(row)
        quality_item = QTableWidgetItem(quality)
        quality_item.setData(Qt.UserRole, fmt_type)
        self.format_table.setItem(row, 0, quality_item)
        self.format_table.setItem(row, 1, QTableWidgetItem(fmt))
        self.format_table.setItem(row, 2, QTableWidgetItem(size))
        self.format_table.setItem(row, 3, QTableWidgetItem(codec))
        self.format_table.setItem(row, 4, QTableWidgetItem(fmt_id))

    def toggle_advanced_view(self):
        self.populate_table()

    def on_selection_changed(self):
        items = self.format_table.selectedItems()
        if items:
            row = items[0].row()
            self.selected_format = self.format_table.item(row, 4).text()
            self.selected_type = self.format_table.item(row, 0).data(Qt.UserRole) or 'video'
            self.download_btn.setEnabled(True)
            self.later_btn.setEnabled(True)
            self._update_path()

    def _update_path(self):
        """Nombre a partir del título; la extensión según sea video o solo audio."""
        audio = self.selected_type == 'audio'
        ext = 'mp3' if audio else 'mp4'
        current = self.path_input.text().strip()
        folder = os.path.dirname(current) or self.folder
        # Al pasar de video a audio (o al revés) cambia de carpeta, salvo que el usuario haya elegido otra
        if os.path.normcase(folder) == os.path.normcase(self.audio_folder if not audio else self.folder):
            folder = self.audio_folder if audio else self.folder
        name = os.path.splitext(os.path.basename(current))[0]
        if not name or name == "video":
            name = safe_title(self.video_title)
        self.path_input.setText(os.path.join(folder, f"{name}.{ext}"))

    def browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar como", self.path_input.text(), "Video (*.mp4);;Audio (*.mp3)")
        if path:
            self.path_input.setText(os.path.normpath(path))

    def on_error(self, msg):
        if not self.isVisible():
            return  # el usuario cerró el diálogo durante el análisis
        QMessageBox.critical(self, "Error", msg)
        self.reject()

    def start_download(self):
        if not self.selected_format:
            return
        self.accept()

    def download_later(self):
        self.start_now = False
        self.start_download()

    def get_download_info(self):
        # Determinar extensión basada en el tipo del formato elegido
        # ("137+bestaudio/137" es video aunque mencione bestaudio)
        ext = 'mp3' if self.selected_type == 'audio' else 'mp4'
        folder = self.audio_folder if ext == 'mp3' else self.folder
        path = self.path_input.text().strip() or os.path.join(folder, f"{safe_title(self.video_title)}.{ext}")
        if os.path.splitext(path)[1].lower() != f".{ext}":
            path = os.path.splitext(path)[0] + f".{ext}"

        # Descargar desde la misma URL y con las mismas cabeceras con las que se analizó
        source = self.video_info.get('_geas_source') or {}
        return {
            'url': source.get('url') or self.url,
            'format_id': self.selected_format,
            'title': self.video_title or 'video',
            'ext': ext,
            'source': source,
            'save_path': unique_path(path),
            'start_now': self.start_now,
        }
