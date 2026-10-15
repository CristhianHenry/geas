# links_dialog.py - "Descargar todos los enlaces" (como en IDM): elegir qué enlaces de una página descargar
import os
from urllib.parse import urljoin, urldefrag

import requests
from bs4 import BeautifulSoup
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal

import icons
import network
from browser_context import DEFAULT_USER_AGENT
from enhanced_downloader import filename_from_url
from file_categories import CATEGORIES, category_of

ALL_TYPES = "Todos los tipos"
OTHER = "Páginas y otros"
COL_CHECK, COL_NAME, COL_TYPE, COL_URL = range(4)


def page_links(url, timeout=20, limit=5000):
    """
    Enlaces de una página (para "Enlaces de página", cuando no viene de la extensión):
    (título, [{'url', 'text'}]). Lanza una excepción si la página no se puede leer.
    """
    response = requests.get(url, headers={"User-Agent": DEFAULT_USER_AGENT}, auth=network.login_for(url),
                            timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    seen, links = set(), []
    for anchor in soup.find_all("a", href=True):
        link = urldefrag(urljoin(response.url, anchor["href"].strip()))[0]
        if not link.lower().startswith(("http://", "https://")) or link in seen:
            continue
        seen.add(link)
        links.append({"url": link, "text": " ".join(anchor.get_text(" ", strip=True).split())[:200]})
        if len(links) >= limit:
            break
    return title, links


class PageLinksThread(QThread):
    """Lee los enlaces de una página sin congelar la interfaz."""
    done = Signal(str, object, str)  # (título, enlaces, error)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            title, links = page_links(self.url)
            self.done.emit(title, links, "")
        except Exception as e:
            self.done.emit("", [], str(e))


class LinksDialog(QDialog):
    """
    Lista los enlaces de una página con una casilla cada uno. Se marcan solos los
    que son archivos (zip, mp4, pdf...); el filtro por texto y por tipo ayuda a
    elegir entre cientos. Se descargan los marcados que están a la vista.
    """

    def __init__(self, links, folder, page_title="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Descargar enlaces" + (f" — {page_title[:80]}" if page_title else ""))
        self.setWindowIcon(icons.icon("add"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(900, 560)
        self.links = links  # [{'url', 'text'}]

        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("Filtrar por nombre, texto o dirección…")
        self.text_filter.textChanged.connect(self.apply_filter)
        self.type_filter = QComboBox()
        self.type_filter.addItems([ALL_TYPES] + [name for name, _, _ in CATEGORIES] + [OTHER])
        self.type_filter.currentTextChanged.connect(self.apply_filter)
        check_all = QPushButton("Marcar los visibles")
        check_all.clicked.connect(lambda: self._set_visible_checked(True))
        check_none = QPushButton("Desmarcar los visibles")
        check_none.clicked.connect(lambda: self._set_visible_checked(False))
        filters.addWidget(self.text_filter, 1)
        filters.addWidget(self.type_filter)
        filters.addWidget(check_all)
        filters.addWidget(check_none)
        layout.addLayout(filters)

        self.table = QTableWidget(len(links), 4)
        self.table.setHorizontalHeaderLabels(["", "Archivo", "Tipo", "Dirección"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_URL, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_NAME, 280)
        for row, link in enumerate(links):
            name = filename_from_url(link["url"]) or link["url"]
            category, icon_name = category_of(name)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if category != "General" else Qt.Unchecked)  # archivos sí, páginas no
            name_item = QTableWidgetItem(icons.icon(icon_name), name)
            name_item.setToolTip(link.get("text") or name)
            self.table.setItem(row, COL_CHECK, check)
            self.table.setItem(row, COL_NAME, name_item)
            self.table.setItem(row, COL_TYPE, QTableWidgetItem(category if category != "General" else OTHER))
            url_item = QTableWidgetItem(link["url"])
            url_item.setToolTip(link["url"])
            self.table.setItem(row, COL_URL, url_item)
        self.table.itemChanged.connect(lambda *_: self._update_count())
        self.table.itemDoubleClicked.connect(self._toggle_row)
        layout.addWidget(self.table)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Guardar en:"))
        self.folder_input = QLineEdit(folder)
        browse = QPushButton(icons.icon("folder"), "Examinar…")
        browse.clicked.connect(self.browse_folder)
        folder_row.addWidget(self.folder_input, 1)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

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

    def apply_filter(self):
        text = self.text_filter.text().strip().lower()
        kind = self.type_filter.currentText()
        for row, link in enumerate(self.links):
            haystack = " ".join((self.table.item(row, COL_NAME).text(), link.get("text") or "", link["url"])).lower()
            matches_type = kind == ALL_TYPES or self.table.item(row, COL_TYPE).text() == kind
            self.table.setRowHidden(row, not (matches_type and text in haystack))
        self._update_count()

    def _set_visible_checked(self, checked):
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                self.table.item(row, COL_CHECK).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _toggle_row(self, item):
        check = self.table.item(item.row(), COL_CHECK)
        check.setCheckState(Qt.Unchecked if check.checkState() == Qt.Checked else Qt.Checked)

    def selected_urls(self):
        """Los enlaces marcados y visibles (lo que se ve es lo que se descarga)."""
        return [self.links[row]["url"] for row in range(self.table.rowCount())
                if not self.table.isRowHidden(row) and self.table.item(row, COL_CHECK).checkState() == Qt.Checked]

    def _update_count(self):
        count = len(self.selected_urls())
        self.count_label.setText(f"Se descargarán {count} de {len(self.links)} enlaces" if count
                                 else f"Marca los enlaces que quieres descargar ({len(self.links)} en la página)")
        self.ok_button.setEnabled(bool(count))

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta", self.folder_input.text())
        if folder:
            self.folder_input.setText(os.path.normpath(folder))

    def folder(self):
        return self.folder_input.text().strip()
