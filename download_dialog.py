# download_dialog.py - Ventana de progreso de una descarga (como la de IDM)
import os
import subprocess
import sys

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QProgressBar,
    QTabWidget, QWidget, QCheckBox, QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QAbstractItemView, QMessageBox
)
from PySide6.QtCore import QTimer, Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QLinearGradient

import icons
from ui_format import format_size, format_speed, format_eta, format_percent, describe_status


def open_path(path):
    """Abre el archivo con su programa predeterminado."""
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def open_with(path):
    """Diálogo de Windows 'Abrir con...'."""
    if sys.platform == "win32":
        subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", path])
    else:
        open_path(path)


def open_folder(path):
    """Abre la carpeta con el archivo seleccionado (o su .part si la descarga no terminó)."""
    if not os.path.exists(path) and os.path.exists(path + ".part"):
        path += ".part"
    if sys.platform == "win32":
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile(os.path.dirname(path) or ".")
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])


class SegmentBar(QWidget):
    """Barra de conexiones de IDM: cada tramo del archivo y cuánto lleva descargado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self.total = 0
        self.fraction = 0.0
        self.setMinimumHeight(22)

    def set_data(self, segments, total, fraction):
        self.segments, self.total, self.fraction = segments, total, fraction
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, QColor("#ffffff"))
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0, QColor("#6db3f2"))
        gradient.setColorAt(1, QColor("#2f7fd3"))
        width = rect.width() - 1
        if self.segments and self.total:
            for segment in self.segments:
                x = 1 + segment["start"] / self.total * width
                filled = min(segment["downloaded"], segment["end"] - segment["start"] + 1) / self.total * width
                painter.fillRect(QRectF(x, 1, filled, rect.height() - 1), gradient)
            painter.setPen(QColor("#8a95a1"))
            for segment in self.segments[1:]:
                x = int(1 + segment["start"] / self.total * width)
                painter.drawLine(x, 1, x, rect.height())
        elif self.fraction:
            painter.fillRect(QRectF(1, 1, width * self.fraction, rect.height() - 1), gradient)
        painter.setPen(QColor("#b9b9b9"))
        painter.drawRect(rect)
        painter.end()


class DownloadDialog(QDialog):
    """Progreso de una descarga; al terminar muestra 'Descarga completada' con Abrir / Abrir carpeta."""

    # Estado de cada conexión (tabla "Conexiones de descarga")
    STATE_TEXT = {"conectando": "Conectando…", "descargando": "Recibiendo datos…", "completado": "Terminada",
                  "reintentando": "Reconectando…", "error": "Error"}

    def __init__(self, task_id, manager, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.manager = manager
        self.output_path = ""
        self.finished_shown = False
        self.setWindowIcon(icons.icon("app"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(540)

        # Dos vistas: progreso y "Descarga completada" (oculta hasta terminar)
        self.progress_page = self._build_progress_page()
        self.finished_page = self._build_finished_page()
        self.finished_page.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.progress_page)
        layout.addWidget(self.finished_page)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    # ------------------------------------------------------------------ construcción

    def _field(self, grid, row, name):
        label = QLabel(name)
        label.setObjectName("FieldName")
        value = QLabel("")
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(label, row, 0, Qt.AlignRight | Qt.AlignTop)
        grid.addWidget(value, row, 1)
        return value

    def _build_progress_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        status_tab = QWidget()
        grid = QGridLayout(status_tab)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(12)
        self.url_value = self._field(grid, 0, "URL:")
        self.url_value.setWordWrap(True)
        self.status_value = self._field(grid, 1, "Estado:")
        self.size_value = self._field(grid, 2, "Tamaño del archivo:")
        self.downloaded_value = self._field(grid, 3, "Descargado:")
        self.speed_value = self._field(grid, 4, "Velocidad de transferencia:")
        self.eta_value = self._field(grid, 5, "Tiempo restante:")
        self.resume_value = self._field(grid, 6, "Capacidad de reanudación:")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        grid.addWidget(self.progress_bar, 7, 0, 1, 2)
        tabs.addTab(status_tab, "Estado de la descarga")

        speed_tab = QWidget()
        speed_layout = QVBoxLayout(speed_tab)
        self.limit_check = QCheckBox("Usar límite de velocidad")
        limit_row = QHBoxLayout()
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 1024 * 1024)
        self.limit_spin.setValue(500)
        self.limit_spin.setSuffix(" KB/s")
        limit_row.addWidget(QLabel("Velocidad máxima:"))
        limit_row.addWidget(self.limit_spin)
        limit_row.addStretch()
        self.limit_hint = QLabel("Se aplica al momento a esta descarga.")
        self.limit_hint.setObjectName("Hint")
        speed_layout.addWidget(self.limit_check)
        speed_layout.addLayout(limit_row)
        speed_layout.addWidget(self.limit_hint)
        speed_layout.addStretch()
        self.limit_check.toggled.connect(self.apply_speed_limit)
        self.limit_spin.valueChanged.connect(self.apply_speed_limit)
        tabs.addTab(speed_tab, "Límite de velocidad")
        self.tabs = tabs
        layout.addWidget(tabs)

        buttons = QHBoxLayout()
        self.details_button = QPushButton("<< Ocultar detalles")
        self.details_button.clicked.connect(self.toggle_details)
        self.pause_button = QPushButton("Pausa")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.cancel_download)
        buttons.addWidget(self.details_button)
        buttons.addStretch()
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.details = QGroupBox("Conexiones de descarga")
        details_layout = QVBoxLayout(self.details)
        self.segment_bar = SegmentBar()
        self.connections = QTableWidget(0, 3)
        self.connections.setHorizontalHeaderLabels(["N.º", "Descargado", "Información"])
        self.connections.verticalHeader().setVisible(False)
        self.connections.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.connections.setSelectionMode(QAbstractItemView.NoSelection)
        self.connections.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.connections.setColumnWidth(0, 50)
        self.connections.setColumnWidth(1, 120)
        self.connections.verticalHeader().setDefaultSectionSize(22)
        self.connections.setMinimumHeight(4 * 22 + 50)  # 4 conexiones visibles sin desplazarse
        details_layout.addWidget(self.segment_bar)
        details_layout.addWidget(self.connections)
        layout.addWidget(self.details)
        return page

    def _build_finished_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icons.icon("finished").pixmap(40, 40))
        title = QLabel("Descarga completada")
        title.setObjectName("DialogTitle")
        header.addWidget(icon_label)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(12)
        self.done_name = self._field(grid, 0, "Archivo:")
        self.done_size = self._field(grid, 1, "Tamaño:")
        self.done_path = self._field(grid, 2, "Guardado en:")
        self.done_path.setWordWrap(True)
        self.done_note = QLabel("")
        self.done_note.setObjectName("Warning")
        self.done_note.setWordWrap(True)
        grid.addWidget(self.done_note, 3, 0, 1, 2)
        layout.addLayout(grid)
        layout.addStretch()

        buttons = QHBoxLayout()
        open_button = QPushButton(icons.icon("open"), "Abrir")
        open_button.setDefault(True)
        open_button.clicked.connect(lambda: self._run(open_path))
        open_with_button = QPushButton("Abrir con…")
        open_with_button.clicked.connect(lambda: self._run(open_with))
        folder_button = QPushButton(icons.icon("folder"), "Abrir carpeta")
        folder_button.clicked.connect(lambda: self._run(open_folder, close=False))
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.close)
        for button in (open_button, open_with_button, folder_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        return page

    # ------------------------------------------------------------------ acciones

    def _task(self):
        return self.manager.tasks.get(self.task_id)

    def _run(self, action, close=True):
        try:
            action(self.output_path)
            if close:
                self.close()
        except OSError as e:
            QMessageBox.warning(self, "Geas", f"No se pudo abrir:\n{e}")

    def toggle_details(self):
        visible = not self.details.isVisible()
        self.details.setVisible(visible)
        self.details_button.setText("<< Ocultar detalles" if visible else "Mostrar detalles >>")
        self.adjustSize()

    def toggle_pause(self):
        status = (self.manager.get_status(self.task_id) or {}).get("status", "")
        if status in ("pausado", "en espera"):
            self.manager.resume_download(self.task_id)
        else:
            self.manager.pause_download(self.task_id)
        self.refresh()

    def cancel_download(self):
        status = (self.manager.get_status(self.task_id) or {}).get("status", "")
        if not status.startswith(("completado", "error", "cancelado")):
            self.manager.cancel_download(self.task_id)
        self.close()

    def apply_speed_limit(self):
        task = self._task()
        worker = getattr(task, "worker", None)
        if worker is not None:
            worker.speed_limit_kbps = self.limit_spin.value() if self.limit_check.isChecked() else 0

    # ------------------------------------------------------------------ actualización

    def refresh(self):
        status = self.manager.get_status(self.task_id)
        if status is None:
            self.timer.stop()
            self.close()
            return

        self.output_path = status["output"]
        name = os.path.basename(self.output_path)
        state = status["status"]
        if state.startswith("completado"):
            self._show_finished(status, name)
            return

        total, downloaded = status["total"], status["downloaded"]
        fraction = downloaded / total if total else status["progress"] / 100
        self.setWindowTitle(f"{int(fraction * 100)} % {name}")
        self.url_value.setText(status["url"] if len(status["url"]) <= 160 else status["url"][:157] + "…")
        self.url_value.setToolTip(status["url"])
        self.status_value.setText(describe_status(state))
        object_name = "Error" if state.startswith("error") else ""
        if self.status_value.objectName() != object_name:
            # El color sale de style.qss (QLabel#Error): hay que volver a aplicar el estilo
            self.status_value.setObjectName(object_name)
            self.status_value.style().unpolish(self.status_value)
            self.status_value.style().polish(self.status_value)
        self.size_value.setText(format_size(total) or "Desconocido")
        self.downloaded_value.setText(f"{format_size(downloaded) or '0 B'} ({format_percent(fraction * 100)})"
                                      if total else (format_size(downloaded) or "—"))
        self.speed_value.setText(format_speed(status["speed_bps"]) or "—")
        self.eta_value.setText(format_eta(status["eta_seconds"]) or "—")
        self.resume_value.setText("Sí" if status["resumable"] else "No")
        if state.startswith("convirtiendo"):
            fraction = status["progress"] / 100
        self.progress_bar.setValue(int(fraction * 1000))
        self.progress_bar.setFormat(format_percent(fraction * 100))

        finished = state.startswith(("error", "cancelado"))
        self.pause_button.setText("Reanudar" if state in ("pausado", "en espera") else "Pausa")
        self.pause_button.setEnabled(not finished and not state.startswith("convirtiendo"))
        self.cancel_button.setText("Cerrar" if finished else "Cancelar")
        self.tabs.setTabEnabled(1, getattr(self._task(), "worker", None) is not None)

        # Barra: cada tramo del archivo (se parten al vuelo); tabla: cada conexión
        segments, connections = status["segments"], status.get("connections") or []
        self.segment_bar.set_data(segments, total, fraction)
        self.connections.setVisible(bool(connections))
        self.connections.setRowCount(len(connections))
        for row, connection in enumerate(connections):
            info = "En pausa" if state == "pausado" and connection["state"] == "descargando" else \
                self.STATE_TEXT.get(connection["state"], connection["state"])
            values = (str(row + 1), format_size(connection["downloaded"]) or "0 B", info)
            for column, value in enumerate(values):
                item = self.connections.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.connections.setItem(row, column, item)
                item.setText(value)

    def _show_finished(self, status, name):
        if self.finished_shown:
            return
        self.finished_shown = True
        self.timer.stop()
        self.setWindowTitle("Descarga completada")
        self.done_name.setText(name)
        self.done_size.setText(format_size(status["total"] or status["downloaded"]) or "—")
        self.done_path.setText(self.output_path)
        note = status["status"][len("completado"):].strip(" ()")
        self.done_note.setText(f"Aviso: {note}" if note else "")
        # Oculta, la vista de progreso (más alta) deja de contar para el tamaño de la ventana
        self.progress_page.hide()
        self.finished_page.show()
        QTimer.singleShot(0, self.adjustSize)  # cuando Qt ya recalculó el diseño
        self.raise_()

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
