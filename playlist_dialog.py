# playlist_dialog.py - Descargar una lista de reproducción o un canal completo con una sola elección de calidad
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog
)
from PySide6.QtCore import Qt

import icons
from enhanced_downloader import sanitize_filename
from media_handler import FORMAT_AUDIO, format_up_to

# (texto, selector de formato de yt-dlp, es solo audio)
QUALITIES = [
    ("1080p", format_up_to(1080), False),
    ("720p", format_up_to(720), False),
    ("480p", format_up_to(480), False),
    ("Máxima (puede necesitar conversión)", "bv*+ba/b", False),
    ("Solo audio (MP3)", FORMAT_AUDIO, True),
]
SUBTITLES = [("Sin subtítulos", None), ("Español", "es"), ("Inglés", "en")]
COL_CHECK, COL_NUMBER, COL_TITLE, COL_DURATION = range(4)


def _duration(seconds):
    if not seconds:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class PlaylistDialog(QDialog):
    """Todos los videos de la lista, marcados; la calidad y los subtítulos se eligen una vez para todos."""

    def __init__(self, playlist, folder, audio_folder=None, subtitle_lang="", parent=None):
        super().__init__(parent)
        self.playlist = playlist  # {'title', 'entries': [{'url', 'title', 'duration'}]}
        self.folder = folder
        self.audio_folder = audio_folder or folder
        entries = playlist["entries"]
        self.setWindowTitle(f"Lista de reproducción — {playlist['title'][:80]}")
        self.setWindowIcon(icons.icon("video"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(820, 600)

        layout = QVBoxLayout(self)
        title = QLabel(playlist["title"])
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        self.table = QTableWidget(len(entries), 4)
        self.table.setHorizontalHeaderLabels(["", "#", "Título", "Duración"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.table.horizontalHeader()
        for column in (COL_CHECK, COL_NUMBER, COL_DURATION):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        for row, entry in enumerate(entries):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked)
            self.table.setItem(row, COL_CHECK, check)
            self.table.setItem(row, COL_NUMBER, QTableWidgetItem(str(row + 1)))
            title_item = QTableWidgetItem(entry["title"])
            title_item.setToolTip(entry["url"])
            self.table.setItem(row, COL_TITLE, title_item)
            self.table.setItem(row, COL_DURATION, QTableWidgetItem(_duration(entry.get("duration"))))
        self.table.itemChanged.connect(lambda *_: self._update_count())
        layout.addWidget(self.table, 1)

        marks = QHBoxLayout()
        all_button = QPushButton("Marcar todos")
        all_button.clicked.connect(lambda: self._set_all(Qt.Checked))
        none_button = QPushButton("Desmarcar todos")
        none_button.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        marks.addWidget(all_button)
        marks.addWidget(none_button)
        marks.addStretch()
        layout.addLayout(marks)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.quality = QComboBox()
        for label, _, _ in QUALITIES:
            self.quality.addItem(label)
        self.quality.currentIndexChanged.connect(self._on_quality_changed)
        self.subtitles = QComboBox()
        for label, lang in SUBTITLES:
            self.subtitles.addItem(label, lang)
        if subtitle_lang:
            index = self.subtitles.findData(subtitle_lang.split("-")[0])
            self.subtitles.setCurrentIndex(max(0, index))
        self.folder_input = QLineEdit(folder)
        browse = QPushButton(icons.icon("folder"), "Examinar…")
        browse.clicked.connect(self.browse_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_input, 1)
        folder_row.addWidget(browse)
        grid.addWidget(QLabel("Calidad:"), 0, 0)
        grid.addWidget(self.quality, 0, 1)
        grid.addWidget(QLabel("Subtítulos:"), 1, 0)
        grid.addWidget(self.subtitles, 1, 1)
        grid.addWidget(QLabel("Guardar en:"), 2, 0)
        grid.addLayout(folder_row, 2, 1)
        layout.addLayout(grid)
        self.make_folder = QCheckBox("Crear una carpeta con el nombre de la lista")
        self.make_folder.setChecked(True)
        self.numbered = QCheckBox("Numerar los archivos en el orden de la lista (001 - …)")
        self.numbered.setChecked(True)
        layout.addWidget(self.make_folder)
        layout.addWidget(self.numbered)

        buttons = QHBoxLayout()
        self.count_label = QLabel()
        buttons.addWidget(self.count_label)
        buttons.addStretch()
        self.ok_button = QPushButton("Descargar")
        self.ok_button.setObjectName("PrimaryButton")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)
        self._update_count()

    def _set_all(self, state):
        for row in range(self.table.rowCount()):
            self.table.item(row, COL_CHECK).setCheckState(state)

    def _on_quality_changed(self):
        audio = QUALITIES[self.quality.currentIndex()][2]
        self.subtitles.setEnabled(not audio)  # un MP3 no lleva subtítulos
        # Video <-> audio: cambia de carpeta (Video / Música), salvo que el usuario haya elegido otra
        current = os.path.normcase(self.folder_input.text().strip())
        if current == os.path.normcase(self.audio_folder if not audio else self.folder):
            self.folder_input.setText(self.audio_folder if audio else self.folder)

    def _update_count(self):
        count = len(self.selected_rows())
        self.count_label.setText(f"Se descargarán {count} de {self.table.rowCount()} videos")
        self.ok_button.setEnabled(bool(count))

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta", self.folder_input.text())
        if folder:
            self.folder_input.setText(os.path.normpath(folder))

    def selected_rows(self):
        return [row for row in range(self.table.rowCount())
                if self.table.item(row, COL_CHECK).checkState() == Qt.Checked]

    def downloads(self):
        """[(url, ruta de destino)] de los videos marcados, en el orden de la lista."""
        _, _, audio = QUALITIES[self.quality.currentIndex()]
        folder = self.folder_input.text().strip() or self.folder
        if self.make_folder.isChecked():
            folder = os.path.join(folder, sanitize_filename(self.playlist["title"], "Lista de reproducción"))
        digits = max(3, len(str(self.table.rowCount())))
        result = []
        for row in self.selected_rows():
            entry = self.playlist["entries"][row]
            name = sanitize_filename(entry["title"], f"video {row + 1}")
            if self.numbered.isChecked():
                name = f"{row + 1:0{digits}d} - {name}"
            result.append((entry["url"], os.path.join(folder, f"{name}.{'mp3' if audio else 'mp4'}")))
        return result

    def format_id(self):
        return QUALITIES[self.quality.currentIndex()][1]

    def subtitle_choice(self):
        """Mismo formato que la ventana de un video; auto=None: los del autor o, si no hay, los automáticos."""
        lang = self.subtitles.currentData()
        if not lang or not self.subtitles.isEnabled():
            return None
        return {"lang": lang, "auto": None, "embed": True}
