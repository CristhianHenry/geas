# scheduler_dialog.py - Programador de descargas (ventana, como en IDM)
import os
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QDateTimeEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog,
    QGroupBox, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, QDateTime

import icons
from enhanced_downloader import filename_from_url
from ui_format import format_date


class SchedulerDialog(QDialog):
    def __init__(self, scheduler, settings, is_valid_url, parent=None):
        super().__init__(parent)
        self.scheduler = scheduler
        self.settings = settings
        self.is_valid_url = is_valid_url
        self.setWindowTitle("Programador")
        self.setWindowIcon(icons.icon("scheduler"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(720, 460)

        layout = QVBoxLayout(self)
        new_group = QGroupBox("Programar una descarga")
        grid = QGridLayout(new_group)
        grid.setColumnStretch(1, 1)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://ejemplo.com/archivo.zip")
        self.url_input.textChanged.connect(self._suggest_path)
        self.path_input = QLineEdit()
        browse = QPushButton("…")
        browse.setObjectName("BrowseButton")
        browse.clicked.connect(self.browse)
        self.time_input = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.time_input.setCalendarPopup(True)
        self.time_input.setDisplayFormat("dd/MM/yyyy HH:mm")
        add_button = QPushButton(icons.icon("scheduler"), "Programar")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self.schedule)
        grid.addWidget(QLabel("URL:"), 0, 0)
        grid.addWidget(self.url_input, 0, 1, 1, 2)
        grid.addWidget(QLabel("Guardar como:"), 1, 0)
        grid.addWidget(self.path_input, 1, 1)
        grid.addWidget(browse, 1, 2)
        grid.addWidget(QLabel("Iniciar el:"), 2, 0)
        grid.addWidget(self.time_input, 2, 1)
        grid.addWidget(add_button, 2, 2)
        layout.addWidget(new_group)

        layout.addWidget(QLabel("Descargas programadas:"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Archivo", "Inicio", "Estado", "URL"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 120)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        remove_button = QPushButton(icons.icon("delete"), "Quitar")
        remove_button.clicked.connect(self.remove_selected)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.close)
        buttons.addWidget(remove_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()

    def _suggest_path(self, url):
        name = filename_from_url(url.strip(), "")
        if name and not self.path_input.isModified():
            self.path_input.setText(os.path.join(self.settings.get("default_download_folder"), name))

    def browse(self):
        start = self.path_input.text() or self.settings.get("default_download_folder")
        path, _ = QFileDialog.getSaveFileName(self, "Guardar como", start, "Todos los archivos (*.*)")
        if path:
            self.path_input.setText(os.path.normpath(path))
            self.path_input.setModified(True)

    def schedule(self):
        url = self.url_input.text().strip()
        path = self.path_input.text().strip()
        start_time = self.time_input.dateTime().toPython()
        if not self.is_valid_url(url):
            QMessageBox.warning(self, "Programador", "La URL no es válida.")
            return
        if not path:
            QMessageBox.warning(self, "Programador", "Indica dónde guardar el archivo.")
            return
        if start_time <= datetime.now():
            QMessageBox.warning(self, "Programador", "La fecha y hora deben ser futuras.")
            return
        self.scheduler.add_task(url, path, start_time, self.settings.get("default_threads"))
        self.url_input.clear()
        self.path_input.clear()
        self.path_input.setModified(False)
        self.refresh()

    def refresh(self):
        tasks = self.scheduler.list_tasks()
        self.table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            values = (os.path.basename(task.get("output_path", "")), format_date(task.get("start_time")),
                      task.get("status", ""), task.get("url", ""))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, task.get("id"))
                self.table.setItem(row, column, item)

    def remove_selected(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        for row in rows:
            task_id = self.table.item(row, 0).data(Qt.UserRole)
            self.scheduler.cancel_task(task_id)
        self.refresh()

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
