import os
from urllib.parse import urlparse

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QProgressBar,
    QGroupBox, QCheckBox, QFileDialog, QAbstractItemView, QComboBox, QWidget
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
import requests

import icons
from enhanced_downloader import unique_path
from media_handler import MediaHandler
from ui_format import format_size


def _needs_conversion(codec):
    """AV1, VP9 o HEVC: Geas lo convertirá a H.264 al terminar (tarda, sobre todo sin gráfica)."""
    return str(codec).lower().startswith(("av01", "av1", "vp9", "vp09", "vp8", "hev", "hvc"))


def safe_title(title):
    """Título apto como nombre de archivo (letras, números y ' .-_()')."""
    cleaned = "".join(c for c in (title or "") if c.isalpha() or c.isdigit() or c in " .-_()").strip(" .")
    return cleaned or "video"


class MediaInfoThread(QThread):
    """Hilo para obtener información del medio sin congelar la UI"""
    info_ready = Signal(object)
    error_occurred = Signal(str)
    playlist_ready = Signal(object)  # la página es una lista: {'title', 'entries'}

    def __init__(self, url, context=None, prefer_stream=False):
        super().__init__()
        self.url = url
        self.context = context
        self.prefer_stream = prefer_stream
        self.handler = MediaHandler()

    def run(self):
        info, errors = self.handler.resolve(self.url, self.context, self.prefer_stream)
        if info:
            # La miniatura se descarga aquí para no bloquear la interfaz
            thumbnail_url = info.get('thumbnail')
            if thumbnail_url:
                try:
                    info['_thumbnail_data'] = requests.get(thumbnail_url, timeout=5).content
                except requests.RequestException:
                    pass
            self.info_ready.emit(info)

        # Después, sin hacer esperar la elección de calidad: ¿es una lista de reproducción o un canal?
        playlist = None
        if self.handler.looks_like_playlist(self.url):
            try:
                playlist = self.handler.playlist_entries(self.url, self.context)
            except Exception as e:
                errors.append(str(e))
        if playlist:
            self.playlist_ready.emit(playlist)
        elif not info:
            message = "No se encontró ningún video descargable en esta página."
            if errors:
                message += "\n\nDetalles:\n" + "\n".join(f"• {e[:200]}" for e in errors[-3:])
            message += ("\n\nSi el sitio cambió hace poco, puede que haga falta una versión nueva de yt-dlp: "
                        "Ayuda → Actualizar yt-dlp.")
            self.error_occurred.emit(message)


class VideoQualityDialog(QDialog):
    PLAYLIST = 2  # resultado de exec(): el usuario eligió descargar la lista completa

    def __init__(self, url, manager, parent=None, context=None, prefer_stream=False, folder=None,
                 convert_note=False, audio_folder=None, subtitle_lang="", ffmpeg=False):
        super().__init__(parent)
        self.url = url
        self.manager = manager
        self.context = context  # BrowserContext cuando la solicitud viene del navegador
        self.prefer_stream = prefer_stream
        self.folder = folder or os.path.expanduser("~/Downloads")
        self.audio_folder = audio_folder or self.folder  # "solo audio" (con carpetas por tipo: Música)
        self.convert_note = convert_note  # avisar que se convertirá a H.264 si hace falta
        self.subtitle_lang = subtitle_lang  # idioma de subtítulos elegido la última vez
        self.ffmpeg = ffmpeg                # con ffmpeg los subtítulos se pueden incrustar
        self.media_handler = MediaHandler()
        self.selected_format = None
        self.selected_type = 'video'
        self.video_info = None
        self.video_title = None
        self.start_now = True
        self.playlist = None  # lista de reproducción a la que pertenece el video, si la hay
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
        self.playlist_button = QPushButton(icons.icon("video"), "")
        self.playlist_button.clicked.connect(lambda: self.done(self.PLAYLIST))
        self.playlist_button.hide()
        info_layout.addWidget(self.playlist_button, 0, Qt.AlignLeft)
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

        # === Subtítulos (solo si el video los ofrece) ===
        self.subs_widget = QWidget()
        subs_layout = QHBoxLayout(self.subs_widget)
        subs_layout.setContentsMargins(0, 0, 0, 0)
        self.subs_combo = QComboBox()
        self.subs_combo.addItem("Sin subtítulos", None)
        self.embed_check = QCheckBox("Incrustar en el video")
        self.embed_check.setChecked(self.ffmpeg)
        self.embed_check.setEnabled(self.ffmpeg)
        self.embed_check.setToolTip("Como una pista que el reproductor muestra o esconde" if self.ffmpeg else
                                    "Requiere ffmpeg: sin él quedan como archivo aparte junto al video")
        subs_layout.addWidget(QLabel("Subtítulos:"))
        subs_layout.addWidget(self.subs_combo, 1)
        subs_layout.addWidget(self.embed_check)
        self.subs_widget.hide()
        layout.addWidget(self.subs_widget)

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
        self.thread.playlist_ready.connect(self.on_playlist_ready)
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

        # Subtítulos: se preselecciona el idioma elegido la última vez, si está
        for option in self.media_handler.subtitle_options(info):
            self.subs_combo.addItem(option['label'], option)
            if self.subtitle_lang and option['lang'] == self.subtitle_lang and self.subs_combo.currentIndex() == 0:
                self.subs_combo.setCurrentIndex(self.subs_combo.count() - 1)
        self.subs_widget.setVisible(self.subs_combo.count() > 1)

        # Obtener ambas listas de formatos
        self.smart_formats = self.media_handler.get_formats(info)
        self.raw_formats = self.media_handler.get_raw_formats(info)
        self.populate_table()

    def on_playlist_ready(self, playlist):
        if not self.isVisible():
            return
        self.playlist = playlist
        if self.video_info is None:
            self.done(self.PLAYLIST)  # la página es solo una lista o un canal: directo a elegir sus videos
            return
        self.playlist_button.setText(f"Descargar la lista completa ({len(playlist['entries'])} videos)…")
        self.playlist_button.setToolTip(playlist['title'])
        self.playlist_button.show()

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
            codec = 'audio' if f['vcodec'] in (None, 'none') else f['vcodec']
            if self.convert_note and f['type'] == 'video' and _needs_conversion(codec):
                codec += " (se convertirá)"  # en una PC lenta conviene otra calidad
            self.add_row(f['resolution'], f['ext'], format_size(size) or "Desconocido", codec, f['format_id'], f['type'])
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
            self.subs_widget.setEnabled(self.selected_type != 'audio')  # un MP3 no lleva subtítulos
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
            'subtitles': self.selected_subtitles(),
        }

    def selected_subtitles(self):
        """{'lang', 'auto', 'embed'} o None (sin subtítulos, o si se eligió solo audio)."""
        option = self.subs_combo.currentData()
        if not option or self.selected_type == 'audio':
            return None
        return {'lang': option['lang'], 'auto': option['auto'],
                'embed': self.embed_check.isEnabled() and self.embed_check.isChecked()}
