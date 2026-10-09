import sys
import os
import re
import logging
import threading
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QAbstractItemView, QToolBar, QMenu, QMessageBox, QDialog, QLabel,
    QSystemTrayIcon, QStyledItemDelegate, QStyle, QStyleOptionViewItem
)
from PySide6.QtCore import QTimer, QObject, Signal, Qt, QSize, QRect, QProcess
from PySide6.QtGui import QAction, QActionGroup, QColor, QLinearGradient, QKeySequence, QBrush, QPalette

import icons
import network
import paths
import power_actions
import ytdlp_updater
from ytdlp_dialog import YtDlpUpdateDialog, VersionCheckThread
import app_updater
from app_update_dialog import AppUpdateDialog, ReleaseCheckThread
from version import __version__
from manager import DownloadManager
from settings import AppSettings
from scheduler import Scheduler
from download_dialog import DownloadDialog, open_path, open_folder
from smart_download_dialog import SmartDownloadDialog
from video_quality_dialog import VideoQualityDialog
from file_info_dialog import FileInfoDialog, UrlProbeThread
from options_dialog import OptionsDialog
from refresh_dialog import RefreshAddressDialog
from links_dialog import LinksDialog
from scheduler_dialog import SchedulerDialog
from simple_dialogs import AddUrlDialog, DeleteDialog, LogWindow, CountdownDialog
from browser_tab import BrowserTab
from browser_context import BrowserContext
from enhanced_downloader import sanitize_filename, unique_path, filename_from_url
from file_categories import CATEGORIES, category_of
from media_handler import find_ffmpeg
from ui_format import format_size, format_speed, format_eta, format_date, format_percent, describe_status
from api_server import start_server

# Tipos que son listas de reproducción (se analizan con yt-dlp, no se descargan tal cual)
STREAM_CONTENT_TYPES = {
    "application/vnd.apple.mpegurl", "application/x-mpegurl",
    "audio/mpegurl", "audio/x-mpegurl", "application/dash+xml"
}

# Columnas de la lista (como en IDM)
COL_NAME, COL_SIZE, COL_STATUS, COL_ETA, COL_SPEED, COL_DATE = range(6)
COLUMNS = ["Nombre de archivo", "Tamaño", "Estado", "Tiempo restante", "Velocidad", "Último intento"]

ID_ROLE = Qt.UserRole            # id de la descarga (columna 0)
STATUS_ROLE = Qt.UserRole + 1    # estado interno (columna 0)
CATEGORY_ROLE = Qt.UserRole + 2  # categoría por tipo de archivo (columna 0)
PROGRESS_ROLE = Qt.UserRole + 3  # porcentaje para la barra (columna Estado)
SORT_ROLE = Qt.UserRole + 4      # valor para ordenar cada columna

# Estados que quedan a medias si Geas se cierra
UNFINISHED_STATES = ("descargando", "en espera", "en cola", "pausado", "esperando", "obteniendo información")
ACTIVE_STATES = ("descargando", "obteniendo información", "esperando")
STOPPABLE_STATES = ACTIVE_STATES + ("en cola",)


class ServerBridge(QObject):
    """API local en un hilo aparte; cada solicitud del navegador llega a la interfaz como señal."""
    download_requested = Signal(object)  # dict enviado por la extensión

    def __init__(self, manager):
        super().__init__()
        # daemon: termina con la aplicación
        self.thread = threading.Thread(target=start_server, args=(manager,),
                                       kwargs={"on_request": self.download_requested.emit}, daemon=True)

    def start(self):
        self.thread.start()


class ProgressDelegate(QStyledItemDelegate):
    """Columna Estado: barra de progreso con el porcentaje para las descargas en curso."""

    def paint(self, painter, option, index):
        progress = index.data(PROGRESS_ROLE)
        if progress is None:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)  # fondo y selección

        painter.save()
        bar = option.rect.adjusted(4, 3, -4, -3)
        painter.setPen(QColor("#b9b9b9"))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(bar.adjusted(0, 0, -1, -1))
        filled = int((bar.width() - 2) * max(0.0, min(float(progress), 100.0)) / 100)
        if filled > 0:
            gradient = QLinearGradient(0, bar.top(), 0, bar.bottom())
            gradient.setColorAt(0, QColor("#b5dafc"))
            gradient.setColorAt(1, QColor("#66adf2"))
            painter.fillRect(QRect(bar.left() + 1, bar.top() + 1, filled, bar.height() - 2), gradient)
        painter.setPen(QColor("#1b1b1b"))
        painter.drawText(bar, Qt.AlignCenter, text)
        painter.restore()


class DownloadItem(QTreeWidgetItem):
    """Fila de la lista; ordena por el valor numérico de cada columna (tamaño, velocidad...)."""

    def __lt__(self, other):
        tree = self.treeWidget()
        column = tree.sortColumn() if tree else 0
        mine, theirs = self.data(column, SORT_ROLE), other.data(column, SORT_ROLE)
        if mine is None or theirs is None or type(mine) is not type(theirs):
            return self.text(column).lower() < other.text(column).lower()
        return mine < theirs


class DownloadApp(QMainWindow):
    def __init__(self):
        super().__init__()

        # Configurar logging: también en geas.log, porque cuando la abre el navegador no hay consola
        log_file = paths.data("geas.log")
        log_handlers = [RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=1, encoding="utf-8")]
        if sys.stderr:
            log_handlers.append(logging.StreamHandler())
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                            handlers=log_handlers)
        self.logger = logging.getLogger(__name__)

        self.items = {}               # id de descarga -> fila de la lista
        self.dialogs = {}             # id de descarga -> ventana de progreso
        self._reported_errors = set()
        self._notified = set()        # descargas cuyo final ya se avisó
        self._size_cache = {}         # tamaño en disco de descargas antiguas sin tamaño registrado
        self._probe_threads = set()   # consultas de enlaces en curso
        self._last_clipboard_text = None
        self._force_quit = False
        self._restarting = False
        self.browser_window = None
        self.address_dialog = None    # "Actualizar dirección" abierto: recibe el próximo enlace del navegador
        self.scheduler_dialog = None
        self.ytdlp_dialog = None
        self.ytdlp_restart_pending = False  # yt-dlp se actualizó: falta reiniciar
        self._ytdlp_check = None
        self._app_check = None
        self.app_release = None       # versión nueva de Geas encontrada al abrir
        self.finish_action = power_actions.NOTHING  # qué hacer al terminar todas las descargas
        self._finish_armed = False    # hubo descargas en curso después de elegir la acción
        self._finish_pending = False  # la cuenta regresiva está abierta

        try:
            self.app_settings = AppSettings()
            network.apply_settings(self.app_settings)  # proxy y usuarios por sitio, antes de cualquier conexión
            self.manager = DownloadManager(max_active=self.app_settings.get("max_simultaneous_downloads"))
            self.scheduler = Scheduler(self.manager)

            self.apply_stylesheet()
            self.setWindowTitle("Geas Download Manager")
            self.setWindowIcon(icons.icon("app"))
            self.resize(1120, 640)

            self.log_window = LogWindow(self)
            self._create_actions()
            self._create_menus()
            self._create_toolbar()
            self._create_central()
            self._create_statusbar()
            self.refresh_list()

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.refresh_list)
            self.timer.start(500)

            # Iniciar servidor API
            self.server = ServerBridge(self.manager)
            self.server.download_requested.connect(self.handle_browser_request)
            self.server.start()

            self.setup_tray_icon()
            self.toggle_clipboard_monitor(self.app_settings.get("clipboard_monitor"))

            # Descargas detenidas al reiniciar Geas (p. ej. tras actualizar yt-dlp): siguen solas
            for entry_id in self.manager.pending_auto_resume():
                if self.manager.can_resume(entry_id):
                    self.resume_entry(entry_id, show_dialog=False, front=False)  # en su orden
                else:
                    self.manager.history.update_entry(entry_id, touch=False, auto_resume=None)
            self._check_ytdlp_updates()
            self._check_app_updates()

        except Exception as e:
            self.logger.error(f"Error al inicializar la aplicación: {e}")
            QMessageBox.critical(self, "Error Fatal", f"No se pudo inicializar la aplicación:\n{str(e)}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Construcción de la ventana
    # ------------------------------------------------------------------

    def apply_stylesheet(self):
        app = QApplication.instance()
        # Selección azul clara (como el Explorador) también donde el estilo no llega, p. ej. el árbol
        palette = app.palette()
        palette.setColor(QPalette.Highlight, QColor("#cce8ff"))
        palette.setColor(QPalette.HighlightedText, QColor("#000000"))
        app.setPalette(palette)
        path = paths.resource("style.qss")
        try:
            with open(path, "r", encoding="utf-8") as f:
                # En toda la aplicación: también en las ventanas sin padre (progreso, navegador)
                app.setStyleSheet(f.read())
        except Exception as e:
            print(f"No se pudo cargar style.qss: {e}")

    def _action(self, icon_name, text, slot, shortcut=None, tip=None):
        action = QAction(icons.icon(icon_name), text, self) if icon_name else QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        action.setToolTip(tip or text)
        return action

    def _create_actions(self):
        self.act_add = self._action("add", "Añadir URL", self.add_url, "Ctrl+N", "Añadir una descarga (Ctrl+N)")
        self.act_resume = self._action("resume", "Reanudar", self.resume_selected, tip="Reanudar las descargas seleccionadas")
        self.act_stop = self._action("stop", "Detener", self.stop_selected, tip="Detener (pausar) las descargas seleccionadas")
        self.act_stop_all = self._action("stop_all", "Detener todas", self.stop_all)
        self.act_resume_all = self._action(None, "Reanudar todas", self.resume_all)
        self.act_delete = self._action("delete", "Eliminar", self.delete_selected, QKeySequence.Delete,
                                       "Quitar las descargas seleccionadas de la lista (Supr)")
        self.act_delete_done = self._action("delete_done", "Eliminar completadas", self.delete_completed,
                                            tip="Quitar de la lista las descargas terminadas")
        self.act_options = self._action("options", "Opciones", self.show_options)
        self.act_scheduler = self._action("scheduler", "Programador", self.show_scheduler)
        self.act_browser = self._action("browser", "Navegador", self.show_browser, tip="Navegador integrado")
        self.act_smart = self._action("smart", "Detector", self.open_smart_detector, tip="Detector inteligente de enlaces")
        self.act_log = self._action("log", "Registro", self.show_log, tip="Registro de actividad")
        self.act_open = self._action("open", "Abrir", self.open_selected)
        self.act_open_folder = self._action("folder", "Abrir carpeta", self.open_selected_folder)
        self.act_progress = self._action("progress", "Mostrar progreso", self.show_selected_progress)
        self.act_redownload = self._action("redownload", "Descargar de nuevo", self.redownload_selected)
        self.act_refresh_address = self._action(None, "Actualizar dirección de descarga…", self.refresh_address_selected,
                                                tip="Enlace nuevo para seguir una descarga cuyo enlace venció")
        self.act_copy_url = self._action("copy", "Copiar URL", self.copy_selected_url)
        self.act_paste = self._action(None, "Pegar URL y descargar", self.paste_and_analyze, "Ctrl+V")
        self.act_quit = self._action(None, "Salir", self.force_quit, "Ctrl+Q")
        self.act_update_ytdlp = self._action("redownload", "Actualizar yt-dlp…", self.show_ytdlp_updater,
                                             tip="Actualizar el componente que reconoce los videos de las páginas")
        self.act_about = self._action("app", "Acerca de Geas", self.show_about)
        self.act_app_update = self._action("redownload", "Buscar actualizaciones de Geas…",
                                           lambda: self.show_app_updater())
        self.act_app_update.setVisible(app_updater.enabled())
        self.act_categories = QAction("Categorías", self, checkable=True, checked=True)
        self.finish_group = QActionGroup(self)  # "Al terminar las descargas": una opción a la vez
        self.finish_actions = {}
        for key, label, _ in power_actions.ACTIONS:
            action = QAction(label, self, checkable=True, checked=(key == power_actions.NOTHING))
            action.triggered.connect(lambda _checked=False, k=key: self.set_finish_action(k))
            self.finish_group.addAction(action)
            self.finish_actions[key] = action

    def _create_menus(self):
        bar = self.menuBar()
        tasks = bar.addMenu("&Tareas")
        tasks.addActions([self.act_add, self.act_paste, self.act_smart])
        tasks.addSeparator()
        tasks.addAction(self.act_quit)

        files = bar.addMenu("&Archivo")
        files.addActions([self.act_open, self.act_open_folder, self.act_progress])
        files.addSeparator()
        files.addActions([self.act_redownload, self.act_refresh_address, self.act_copy_url])
        files.addSeparator()
        files.addAction(self.act_delete)

        downloads = bar.addMenu("&Descargas")
        downloads.addActions([self.act_resume, self.act_stop])
        downloads.addSeparator()
        downloads.addActions([self.act_resume_all, self.act_stop_all])
        self.finish_menu = downloads.addMenu("Al terminar las descargas")
        self.finish_menu.addActions(list(self.finish_actions.values()))
        downloads.addSeparator()
        downloads.addAction(self.act_delete_done)
        downloads.addSeparator()
        downloads.addActions([self.act_scheduler, self.act_options])

        view = bar.addMenu("&Ver")
        view.addAction(self.act_categories)
        view.addSeparator()
        view.addActions([self.act_browser, self.act_log])

        help_menu = bar.addMenu("A&yuda")
        help_menu.addActions([self.act_app_update, self.act_update_ytdlp])
        help_menu.addSeparator()
        help_menu.addAction(self.act_about)

    def _create_toolbar(self):
        toolbar = QToolBar("Barra de herramientas")
        toolbar.setObjectName("MainToolBar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(32, 32))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.addActions([self.act_add, self.act_resume, self.act_stop, self.act_stop_all,
                            self.act_delete, self.act_delete_done])
        toolbar.addSeparator()
        toolbar.addActions([self.act_options, self.act_scheduler])
        toolbar.addSeparator()
        toolbar.addActions([self.act_browser, self.act_smart, self.act_log])
        self.addToolBar(toolbar)

    def _create_central(self):
        # Categorías (izquierda)
        self.category_tree = QTreeWidget()
        self.category_tree.setObjectName("CategoryTree")
        self.category_tree.setHeaderHidden(True)
        self.category_tree.setIndentation(14)
        self.category_tree.setIconSize(QSize(16, 16))
        self.category_items = {}

        def add_category(parent, key, text, icon_name):
            item = QTreeWidgetItem([text])
            item.setIcon(0, icons.icon(icon_name))
            item.setData(0, Qt.UserRole, key)
            item.setData(0, Qt.UserRole + 1, text)  # nombre sin el contador
            (parent.addChild(item) if parent else self.category_tree.addTopLevelItem(item))
            self.category_items[key] = item
            return item

        all_item = add_category(None, "all", "Todas las descargas", "all")
        for name, icon_name, _ in CATEGORIES:
            add_category(all_item, f"cat:{name}", name, icon_name)
        add_category(None, "unfinished", "Sin terminar", "unfinished")
        add_category(None, "finished", "Terminadas", "finished")
        self.category_tree.expandAll()
        self.category_tree.setCurrentItem(all_item)
        self.category_tree.currentItemChanged.connect(lambda *_: self.apply_filter())
        self.act_categories.toggled.connect(self.category_tree.setVisible)

        # Lista de descargas
        self.list = QTreeWidget()
        self.list.setColumnCount(len(COLUMNS))
        self.list.setHeaderLabels(COLUMNS)
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(16, 16))
        self.list.setItemDelegateForColumn(COL_STATUS, ProgressDelegate(self.list))
        self.list.setSortingEnabled(True)
        self.list.sortByColumn(COL_DATE, Qt.DescendingOrder)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.show_list_menu)
        self.list.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.list.itemSelectionChanged.connect(self.update_actions)
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for column, width in ((COL_SIZE, 90), (COL_STATUS, 170), (COL_ETA, 105), (COL_SPEED, 100), (COL_DATE, 120)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.list.setColumnWidth(column, width)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.category_tree)
        splitter.addWidget(self.list)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([210, 910])
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

    def _create_statusbar(self):
        self.status_label = QLabel("Listo")
        self.statusBar().addWidget(self.status_label, 1)
        self.ytdlp_label = QLabel()
        self.ytdlp_label.setTextFormat(Qt.RichText)
        self.ytdlp_label.linkActivated.connect(lambda _: self.show_ytdlp_updater())
        self.statusBar().addPermanentWidget(self.ytdlp_label)
        self.app_update_label = QLabel()
        self.app_update_label.setTextFormat(Qt.RichText)
        self.app_update_label.linkActivated.connect(lambda _: self.show_app_updater(self.app_release))
        self.app_update_label.hide()
        self.statusBar().addPermanentWidget(self.app_update_label)
        self.ffmpeg_label = QLabel()
        self.statusBar().addPermanentWidget(self.ffmpeg_label)
        self._update_ffmpeg_label()
        self._update_ytdlp_label()

    def _update_ffmpeg_label(self):
        folder = find_ffmpeg()
        self.ffmpeg_label.setText("ffmpeg: listo" if folder else "ffmpeg: no instalado")
        self.ffmpeg_label.setToolTip(folder or "Sin ffmpeg los videos no se reempaquetan ni se convierten a H.264.\n"
                                               "Instálalo con: winget install --id Gyan.FFmpeg.Essentials -e")

    # ------------------------------------------------------------------
    # Lista de descargas
    # ------------------------------------------------------------------

    def _row_values(self, entry, live):
        """(ruta, estado interno, texto de estado, % para la barra o None, tamaño, velocidad, tiempo restante)"""
        if live:
            status, total, downloaded = live["status"], live["total"], live["downloaded"]
            percent = downloaded / total * 100 if total else float(live["progress"])
            if status.startswith("convirtiendo"):
                return live["output"], status, describe_status(status), float(live["progress"]), total, 0, None
            if status == "descargando":
                return (live["output"], status, format_percent(percent), percent, total,
                        live["speed_bps"], live["eta_seconds"])
            if status == "pausado" and percent:
                return live["output"], status, f"En pausa ({format_percent(percent)})", percent, total, 0, None
            return live["output"], status, describe_status(status), None, total, 0, None

        status = entry.get("status", "")
        if status in UNFINISHED_STATES:
            status = "interrumpida"  # quedó a medias en una sesión anterior
        path = entry.get("output_path", "")
        size = entry.get("size") or 0
        percent = self._resume_percent(entry.get("resume"))
        if percent is not None and status in ("interrumpida", "cancelado"):
            # Se reanuda desde ahí: se muestra cuánto lleva, como en IDM
            return (path, status, f"{describe_status(status)} ({format_percent(percent)})", percent,
                    entry["resume"]["total_size"], 0, None)
        if not size and status.startswith("completado"):
            # Las versiones anteriores guardaban 0: se toma del archivo (una vez por descarga)
            if entry["id"] not in self._size_cache:
                self._size_cache[entry["id"]] = os.path.getsize(path) if os.path.isfile(path) else 0
            size = self._size_cache[entry["id"]]
        return path, status, describe_status(status), None, size, 0, None

    @staticmethod
    def _resume_percent(resume):
        """Porcentaje ya descargado según el avance guardado, o None si no hay uno válido."""
        try:
            done = sum(int(segment[2]) for segment in resume["segments"])
            return min(100.0, done / int(resume["total_size"]) * 100)
        except (TypeError, KeyError, IndexError, ValueError, ZeroDivisionError):
            return None

    def _fill_item(self, item, entry, live):
        path, status, text, progress, total, speed, eta = self._row_values(entry, live)
        name = os.path.basename(path) or entry.get("url", "")
        category, icon_name = category_of(path)

        item.setData(COL_NAME, ID_ROLE, entry["id"])
        item.setData(COL_NAME, STATUS_ROLE, status)
        item.setData(COL_NAME, CATEGORY_ROLE, category)
        item.setText(COL_NAME, name)
        item.setIcon(COL_NAME, icons.icon(icon_name))
        item.setToolTip(COL_NAME, f"{path}\n{entry.get('url', '')}")
        item.setData(COL_NAME, SORT_ROLE, name.lower())

        item.setText(COL_SIZE, format_size(total))
        item.setData(COL_SIZE, SORT_ROLE, int(total or 0))

        item.setText(COL_STATUS, text)
        item.setToolTip(COL_STATUS, text)
        item.setData(COL_STATUS, PROGRESS_ROLE, progress)
        item.setData(COL_STATUS, SORT_ROLE, text.lower())
        item.setForeground(COL_STATUS, QBrush(QColor("#c42b1c" if status.startswith("error") else "#1b1b1b")))

        item.setText(COL_ETA, format_eta(eta))
        item.setData(COL_ETA, SORT_ROLE, float(eta) if eta is not None else float("inf"))
        item.setText(COL_SPEED, format_speed(speed))
        item.setData(COL_SPEED, SORT_ROLE, float(speed or 0))
        item.setText(COL_DATE, format_date(entry.get("timestamp")))
        item.setData(COL_DATE, SORT_ROLE, entry.get("timestamp") or "")

    def refresh_list(self):
        """Sincroniza la lista con el registro de descargas y el progreso de las tareas en curso."""
        try:
            entries = self.manager.history.get_history()
            live = {task_id: self.manager.get_status(task_id) for task_id in list(self.manager.tasks)}
            seen = set()
            for entry in entries:
                entry_id = entry["id"]
                seen.add(entry_id)
                item = self.items.get(entry_id)
                if item is None:
                    item = DownloadItem()
                    self.list.addTopLevelItem(item)
                    self.items[entry_id] = item
                self._fill_item(item, entry, live.get(entry_id))
                self._watch_task(entry_id, live.get(entry_id))
            for entry_id in [i for i in self.items if i not in seen]:
                item = self.items.pop(entry_id)
                self.list.takeTopLevelItem(self.list.indexOfTopLevelItem(item))
            self.apply_filter()
            self._update_counts(live)
            self.update_actions()
        except Exception as e:
            self.logger.error(f"Error actualizando la lista: {e}")

    def _watch_task(self, task_id, live):
        """Anota errores y avisa al terminar (una sola vez por descarga)."""
        if not live:
            return
        status = live["status"]
        name = os.path.basename(live["output"])
        if status.startswith("error") and task_id not in self._reported_errors:
            self._reported_errors.add(task_id)
            self.log_message(f"Error en la descarga {name}: {status}")
        elif status.startswith("completado") and task_id not in self._notified:
            self._notified.add(task_id)
            self.log_message(f"Descarga completada: {name}")
            self.notify("Descarga completada", name)

    def apply_filter(self):
        current = self.category_tree.currentItem()
        key = current.data(0, Qt.UserRole) if current else "all"
        for item in self.items.values():
            finished = (item.data(COL_NAME, STATUS_ROLE) or "").startswith("completado")
            if key == "all":
                visible = True
            elif key == "finished":
                visible = finished
            elif key == "unfinished":
                visible = not finished
            else:
                visible = key == f"cat:{item.data(COL_NAME, CATEGORY_ROLE)}"
            item.setHidden(not visible)

    def _update_counts(self, live):
        counts = {"all": len(self.items), "finished": 0, "unfinished": 0}
        for item in self.items.values():
            finished = (item.data(COL_NAME, STATUS_ROLE) or "").startswith("completado")
            counts["finished" if finished else "unfinished"] += 1
            key = f"cat:{item.data(COL_NAME, CATEGORY_ROLE)}"
            counts[key] = counts.get(key, 0) + 1
        for key, tree_item in self.category_items.items():
            base = tree_item.data(0, Qt.UserRole + 1)
            count = counts.get(key, 0)
            tree_item.setText(0, f"{base} ({count})" if count else base)

        active = [s for s in live.values() if s and (s["status"] in ACTIVE_STATES or s["status"].startswith("convirtiendo"))]
        waiting = sum(1 for s in live.values() if s and s["status"] in ("en espera", "pausado"))
        queued = self.manager.queued_count()
        if active:
            speed = sum(s["speed_bps"] or 0 for s in active)
            text = f"{len(active)} descargando · {format_speed(speed) or '0 B/s'}"
        else:
            text = "Listo"
        if queued:
            text += f" · {queued} en cola (máximo {self.manager.max_active} a la vez)"
        if waiting:
            text += f" · {waiting} en pausa o en espera"
        if self.finish_action != power_actions.NOTHING:
            text += f" · Al terminar: {power_actions.LABELS[self.finish_action]}"
        self.status_label.setText(text)
        self._check_finish_action(len(active) + queued)

    # ------------------------------------------------------------------
    # Al terminar las descargas: cerrar Geas, suspender o apagar el equipo
    # ------------------------------------------------------------------

    def set_finish_action(self, action):
        self.finish_action = action
        self.finish_actions[action].setChecked(True)
        self._finish_armed = False
        if action != power_actions.NOTHING:
            self.log_message(f"Al terminar las descargas: {power_actions.LABELS[action]}")

    def _check_finish_action(self, pending):
        """Con una acción elegida, la ejecuta cuando ya no queda nada descargando ni en cola."""
        if self.finish_action == power_actions.NOTHING or self._finish_pending:
            return
        if pending:
            self._finish_armed = True  # hubo descargas después de elegirla
        elif self._finish_armed:
            self._finish_armed = False
            self._finish_pending = True
            QTimer.singleShot(0, self._run_finish_action)  # fuera del refresco de la lista

    def _run_finish_action(self):
        action = self.finish_action
        dialog = CountdownDialog(power_actions.COUNTDOWN_TEXT[action], 30, self)
        accepted = dialog.exec() == QDialog.Accepted
        self._finish_pending = False
        self.set_finish_action(power_actions.NOTHING)  # se usa una sola vez
        if not accepted:
            self.log_message("Acción al terminar cancelada")
            return
        self.log_message(f"Descargas terminadas: {power_actions.LABELS[action]}")
        if action == power_actions.SLEEP:
            power_actions.sleep_computer()
        elif action == power_actions.SHUTDOWN:
            power_actions.shutdown_computer()  # Windows espera 15 s: Geas se cierra guardando todo
            self.force_quit()
        elif action == power_actions.QUIT:
            self.force_quit()

    def selected_ids(self):
        return [item.data(COL_NAME, ID_ROLE) for item in self.list.selectedItems()]

    def _status_of(self, entry_id):
        item = self.items.get(entry_id)
        return (item.data(COL_NAME, STATUS_ROLE) if item else "") or ""

    def _path_of(self, entry_id):
        live = self.manager.get_status(entry_id)
        if live:
            return live["output"]
        entry = self.manager.history.get_entry(entry_id)
        return entry.get("output_path") if entry else None

    def update_actions(self):
        ids = self.selected_ids()
        statuses = [self._status_of(i) for i in ids]
        resumable = ("pausado", "en espera", "interrumpida")
        self.act_open.setEnabled(any(s.startswith("completado") for s in statuses))
        for action in (self.act_open_folder, self.act_copy_url, self.act_delete, self.act_redownload):
            action.setEnabled(bool(ids))
        self.act_resume.setEnabled(any(s in resumable or s.startswith(("error", "cancelado")) for s in statuses))
        self.act_stop.setEnabled(any(s in STOPPABLE_STATES or s.startswith("convirtiendo") for s in statuses))
        self.act_progress.setEnabled(any(i in self.manager.tasks for i in ids))
        self.act_refresh_address.setEnabled(len(ids) == 1 and self._can_refresh_address(ids[0], statuses[0]))

    def _can_refresh_address(self, entry_id, status):
        """Descargas directas sin terminar que no están bajando ahora (en pausa, interrumpidas, con error...)."""
        entry = self.manager.history.get_entry(entry_id) or {}
        return (entry.get("kind") == "file"
                and (status in ("pausado", "en espera", "en cola", "interrumpida")
                     or status.startswith(("error", "cancelado"))))

    def show_list_menu(self, position):
        menu = QMenu(self)
        if self.list.itemAt(position):
            menu.addActions([self.act_open, self.act_open_folder, self.act_progress])
            menu.addSeparator()
            menu.addActions([self.act_resume, self.act_stop, self.act_redownload, self.act_refresh_address])
            menu.addSeparator()
            menu.addActions([self.act_copy_url, self.act_delete])
        else:
            menu.addActions([self.act_add, self.act_paste])
        menu.exec(self.list.viewport().mapToGlobal(position))

    def on_item_double_clicked(self, item, column):
        entry_id = item.data(COL_NAME, ID_ROLE)
        status = item.data(COL_NAME, STATUS_ROLE) or ""
        if status.startswith("completado"):
            self.open_selected()
        elif entry_id in self.manager.tasks:
            self.show_progress_dialog(entry_id)
        elif self.manager.can_resume(entry_id):
            reply = QMessageBox.question(self, "Geas", "Esta descarga no terminó. ¿Reanudarla desde donde quedó?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.resume_entry(entry_id)
        else:
            reply = QMessageBox.question(self, "Geas", "Esta descarga no terminó. ¿Descargarla de nuevo?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.redownload(entry_id)

    # ------------------------------------------------------------------
    # Acciones de la barra y los menús
    # ------------------------------------------------------------------

    def add_url(self):
        dialog = AddUrlDialog(self)
        if dialog.exec() == QDialog.Accepted and dialog.url():
            self.process_new_url(dialog.url())

    def paste_and_analyze(self):
        text = QApplication.clipboard().text().strip()
        if self.is_valid_url(text):
            self.process_new_url(text)
        else:
            self.add_url()

    def process_new_url(self, url):
        """Descarga añadida a mano: video de una página o archivo (se consulta la URL para saberlo)."""
        if not self.is_valid_url(url):
            QMessageBox.warning(self, "Geas", "La URL no es válida. Debe comenzar con http:// o https://")
            return
        if self.is_video_url(url):
            self.show_video_quality_dialog(url)
        else:
            self.probe_browser_link(url, BrowserContext(), ask=True)

    def resume_selected(self):
        for entry_id in self.selected_ids():
            status = self._status_of(entry_id)
            if entry_id in self.manager.tasks and status in ("pausado", "en espera"):
                self.manager.resume_download(entry_id)
            elif status == "interrumpida" or status.startswith(("error", "cancelado")):
                self.resume_entry(entry_id)
        self.refresh_list()

    def resume_entry(self, entry_id, show_dialog=True, front=True):
        """Continúa una descarga a medias desde donde quedó; sin datos para hacerlo, la descarga de nuevo."""
        if not self.manager.can_resume(entry_id):
            self.redownload(entry_id)
            return
        resumed = self.manager.resume_entry(
            entry_id,
            threads=self.app_settings.get("default_threads"),
            speed_limit_kbps=max(0, self.app_settings.get("download_speed_limit_kbps")),
            max_retries=self.app_settings.get("auto_retry_count"),
            front=front)
        if resumed:
            self.log_message(f"Reanudando: {os.path.basename(self._path_of(entry_id) or '')}")
            if show_dialog and self.app_settings.get("show_progress_dialog"):
                self.show_progress_dialog(entry_id)

    def stop_selected(self):
        for entry_id in self.selected_ids():
            status = self._status_of(entry_id)
            if entry_id in self.manager.tasks and (status in STOPPABLE_STATES or status.startswith("convirtiendo")):
                self.manager.pause_download(entry_id)
        self.refresh_list()

    def stop_all(self):
        # Primero las de la cola: si no, ocuparían el lugar de las que se van deteniendo
        statuses = {task_id: (self.manager.get_status(task_id) or {}).get("status", "")
                    for task_id in list(self.manager.tasks)}
        for task_id in sorted(statuses, key=lambda t: statuses[t] != "en cola"):
            status = statuses[task_id]
            if status in STOPPABLE_STATES or status.startswith("convirtiendo"):
                self.manager.pause_download(task_id)
        self.log_message("Todas las descargas detenidas")
        self.refresh_list()

    def resume_all(self):
        for task_id in list(self.manager.tasks):
            if (self.manager.get_status(task_id) or {}).get("status") in ("pausado", "en espera"):
                self.manager.resume_download(task_id, front=False)  # en su orden, al final de la cola
        self.log_message("Todas las descargas reanudadas")
        self.refresh_list()

    def delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        dialog = DeleteDialog(len(ids), self)
        if dialog.exec() != QDialog.Accepted:
            return
        delete_files = dialog.delete_files.isChecked()
        for entry_id in ids:
            path = self._path_of(entry_id)
            self.manager.remove_task(entry_id)  # la cancela si seguía en curso
            dialog_window = self.dialogs.pop(entry_id, None)
            if dialog_window:
                dialog_window.close()
            if delete_files and path:
                self._delete_file(path)
        self.manager.history.remove_entries(ids)
        self.log_message(f"Eliminadas {len(ids)} descargas de la lista")
        self.refresh_list()

    def _delete_file(self, path, attempts=4):
        """Borra el archivo (y el parcial de yt-dlp). Si la descarga recién cancelada aún lo tiene abierto, reintenta."""
        pending = False
        for candidate in (path, path + ".part"):
            try:
                if os.path.isfile(candidate):
                    os.remove(candidate)
            except OSError:
                pending = True
        if pending and attempts > 1:
            QTimer.singleShot(1000, lambda: self._delete_file(path, attempts - 1))
        elif pending:
            self.log_message(f"No se pudo borrar {path}: está en uso")

    def delete_completed(self):
        ids = [entry_id for entry_id in self.items if self._status_of(entry_id).startswith("completado")]
        if not ids:
            return
        for entry_id in ids:
            self.manager.remove_task(entry_id)
        self.manager.history.remove_entries(ids)
        self.log_message(f"Eliminadas {len(ids)} descargas completadas de la lista")
        self.refresh_list()

    def open_selected(self):
        ids = self.selected_ids()
        path = self._path_of(ids[0]) if ids else None
        if path and os.path.exists(path):
            try:
                open_path(path)
            except OSError as e:
                QMessageBox.warning(self, "Geas", f"No se pudo abrir el archivo:\n{e}")
        else:
            QMessageBox.information(self, "Geas", "El archivo ya no existe en el disco.")

    def open_selected_folder(self):
        ids = self.selected_ids()
        path = self._path_of(ids[0]) if ids else None
        if path:
            open_folder(path)

    def copy_selected_url(self):
        urls = []
        for entry_id in self.selected_ids():
            entry = self.manager.history.get_entry(entry_id)
            if entry:
                urls.append(entry["url"])
        if urls:
            text = "\n".join(urls)
            self._last_clipboard_text = text  # que el monitor de portapapeles no lo tome como descarga nueva
            QApplication.clipboard().setText(text)

    def show_selected_progress(self):
        for entry_id in self.selected_ids():
            if entry_id in self.manager.tasks:
                self.show_progress_dialog(entry_id)
                return

    def redownload_selected(self):
        for entry_id in self.selected_ids():
            self.redownload(entry_id)

    def redownload(self, entry_id):
        """Vuelve a descargar desde la URL guardada (reemplaza la fila anterior)."""
        entry = self.manager.history.get_entry(entry_id)
        if not entry:
            return
        kind = entry.get("kind")
        if kind == "video":
            self.show_video_quality_dialog(entry["url"], replace_entry=entry_id)
        elif kind == "file":
            # Con las cookies y cabeceras guardadas, si la descarga no había terminado
            headers, cookies = self.manager.entry_credentials(entry_id)
            self.manager.remove_task(entry_id)
            self.manager.history.remove_entries([entry_id])
            self.start_file_download(entry["url"], entry["output_path"], headers=headers, cookies=cookies)
        else:
            # Entradas de versiones anteriores (sin tipo): se consulta la URL, como en "Añadir URL"
            self.process_new_url(entry["url"])

    def refresh_address_selected(self):
        ids = self.selected_ids()
        entry = self.manager.history.get_entry(ids[0]) if len(ids) == 1 else None
        if not entry or not self._can_refresh_address(entry["id"], self._status_of(entry["id"])):
            return
        headers, _ = self.manager.entry_credentials(entry["id"])
        referer = next((v for k, v in (headers or {}).items() if k.lower() == "referer"), None)
        expected = (entry.get("resume") or {}).get("total_size") or entry.get("size") or 0
        dialog = RefreshAddressDialog(entry, expected, referer, self)
        self.address_dialog = dialog
        try:
            accepted = dialog.exec() == QDialog.Accepted and dialog.url()
        finally:
            self.address_dialog = None
        if not accepted:
            return
        if self.manager.change_address(entry["id"], dialog.url(), dialog.headers, dialog.cookies):
            self.log_message(f"Dirección actualizada: {os.path.basename(entry.get('output_path', ''))}")
            self.resume_entry(entry["id"])
            self.refresh_list()

    def show_progress_dialog(self, task_id):
        dialog = self.dialogs.get(task_id)
        if dialog is None or not dialog.isVisible():
            # Ventana propia (como en IDM), no modal
            dialog = DownloadDialog(task_id, self.manager)
            self.dialogs[task_id] = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_options(self):
        dialog = OptionsDialog(self.app_settings, self, update_ytdlp=self.show_ytdlp_updater)
        if dialog.exec() == QDialog.Accepted:
            self.manager.set_max_active(self.app_settings.get("max_simultaneous_downloads"))
            network.apply_settings(self.app_settings)
            self.toggle_clipboard_monitor(self.app_settings.get("clipboard_monitor"))
            self._update_ffmpeg_label()
            self.log_message("Opciones actualizadas")

    # ------------------------------------------------------------------
    # yt-dlp: aviso de versión nueva, actualización y reinicio
    # ------------------------------------------------------------------

    def show_ytdlp_updater(self):
        if self.ytdlp_dialog is None:
            self.ytdlp_dialog = YtDlpUpdateDialog(self)
            self.ytdlp_dialog.log.connect(self.log_message)
            self.ytdlp_dialog.updated.connect(self._on_ytdlp_updated)
            self.ytdlp_dialog.restart_requested.connect(self.restart_app)
        self.ytdlp_dialog.check()
        self.ytdlp_dialog.show()
        self.ytdlp_dialog.raise_()
        self.ytdlp_dialog.activateWindow()

    def _on_ytdlp_updated(self, version):
        self.ytdlp_restart_pending = True
        self.app_settings.set("ytdlp_latest_seen", version)
        self._update_ytdlp_label()
        self.notify("yt-dlp actualizado", f"Versión {version}. Reinicia Geas para usarla.")

    def _check_app_updates(self):
        """Una vez al día, si Geas está instalada, comprueba en segundo plano si hay una versión nueva."""
        if not (app_updater.enabled() and self.app_settings.get("check_app_updates")):
            return
        try:
            last = datetime.fromisoformat(self.app_settings.get("app_last_check") or "")
            if datetime.now() - last < timedelta(days=1):
                return
        except ValueError:
            pass
        self._app_check = ReleaseCheckThread(self)
        self._app_check.checked.connect(self._on_app_checked)
        self._app_check.start()

    def _on_app_checked(self, release, error):
        if error:
            self.logger.info(f"No se pudo comprobar si hay una versión nueva de Geas: {error}")
            return
        self.app_settings.set("app_last_check", datetime.now().isoformat(timespec="seconds"))
        if app_updater.is_update(release):
            self.app_release = release
            self.app_update_label.setText(f'<a href="#">Geas {release["version"]} disponible</a>')
            self.app_update_label.show()
            self.log_message(f"Hay una versión nueva de Geas ({release['version']}): Ayuda → Buscar actualizaciones")

    def show_app_updater(self, release=None):
        dialog = AppUpdateDialog(self, release)
        dialog.install_requested.connect(self.install_app_update)
        dialog.exec()

    def install_app_update(self, installer):
        """Detiene las descargas (siguen solas al volver), abre el instalador y cierra Geas para que la reemplace."""
        self.log_message(f"Instalando la actualización: {os.path.basename(installer)}")
        self.manager.shutdown(resume_on_start=True)
        app_updater.run_installer(installer)
        self._restarting = True  # ya se preguntó y se detuvieron
        self.force_quit()

    def _check_ytdlp_updates(self):
        """Una vez al día, comprueba en segundo plano si hay una versión nueva de yt-dlp."""
        if not self.app_settings.get("check_ytdlp_updates"):
            return
        try:
            last = datetime.fromisoformat(self.app_settings.get("ytdlp_last_check") or "")
            if datetime.now() - last < timedelta(days=1):
                return
        except ValueError:
            pass
        self._ytdlp_check = VersionCheckThread(self)
        self._ytdlp_check.checked.connect(self._on_ytdlp_checked)
        self._ytdlp_check.start()

    def _on_ytdlp_checked(self, latest, error):
        if error:
            self.logger.info(f"No se pudo comprobar la versión de yt-dlp: {error}")
            return
        self.app_settings.set("ytdlp_last_check", datetime.now().isoformat(timespec="seconds"))
        self.app_settings.set("ytdlp_latest_seen", latest)
        self._update_ytdlp_label()
        if ytdlp_updater.is_newer(latest, ytdlp_updater.installed_version()):
            self.log_message(f"Hay una versión nueva de yt-dlp ({latest}): Ayuda → Actualizar yt-dlp")

    def _update_ytdlp_label(self):
        installed = ytdlp_updater.installed_version()
        latest = self.app_settings.get("ytdlp_latest_seen") or ""
        if self.ytdlp_restart_pending:
            text = '<a href="#">yt-dlp: reinicia Geas</a>'
            tip = "yt-dlp se actualizó: reinicia Geas para usar la versión nueva"
        elif self.app_settings.get("check_ytdlp_updates") and ytdlp_updater.is_newer(latest, installed):
            text = '<a href="#">yt-dlp: actualización disponible</a>'
            tip = f"Instalada: {installed} · Nueva: {latest}"
        else:
            text = f"yt-dlp {installed or 'no instalado'}"
            tip = "Componente que reconoce los videos de las páginas (Ayuda → Actualizar yt-dlp)"
        self.ytdlp_label.setText(text)
        self.ytdlp_label.setToolTip(tip)

    def _active_downloads(self):
        return [s for s in self.manager.list_all()
                if s and (s["status"] in ACTIVE_STATES or s["status"].startswith("convirtiendo"))]

    def restart_app(self):
        """Reinicia Geas (p. ej. tras actualizar yt-dlp). Las descargas en curso continúan solas al volver."""
        active = self._active_downloads()
        if active:
            reply = QMessageBox.question(
                self, "Reiniciar Geas",
                f"Hay {len(active)} descarga(s) en curso. Se detendrán un momento y continuarán solas al "
                f"reiniciar.\n¿Reiniciar ahora?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply != QMessageBox.Yes:
                return
        self.manager.shutdown(resume_on_start=True)
        # Instalada, sys.executable es Geas.exe; desde el código, Python con main.py
        script = [] if paths.FROZEN else [os.path.join(paths.APP_DIR, "main.py")]
        QProcess.startDetached(sys.executable, script + ["--restart-from", str(os.getpid())], paths.APP_DIR)
        self._restarting = True
        self.force_quit()

    def show_scheduler(self):
        if self.scheduler_dialog is None:
            self.scheduler_dialog = SchedulerDialog(self.scheduler, self.app_settings, self.is_valid_url, self)
        self.scheduler_dialog.show()
        self.scheduler_dialog.raise_()
        self.scheduler_dialog.activateWindow()
        self.scheduler_dialog.timer.start(2000)

    def show_browser(self):
        # Se crea al abrirlo por primera vez: el motor web tarda en arrancar
        if self.browser_window is None:
            self.browser_window = BrowserTab()
            self.browser_window.setWindowTitle("Geas - Navegador")
            self.browser_window.setWindowIcon(icons.icon("browser"))
            self.browser_window.resize(1100, 720)
            self.browser_window.video_detected.connect(self.on_browser_video_detected)
        self.browser_window.show()
        self.browser_window.raise_()
        self.browser_window.activateWindow()

    def show_log(self):
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def show_about(self):
        QMessageBox.about(self, "Acerca de Geas",
                          f"<b>Geas Download Manager {__version__}</b> · <i>Grab Everything At Speed</i><br>"
                          "Gestor de descargas con integración para Chrome y Edge.<br><br>"
                          "Descargas multi-conexión, videos con yt-dlp (HLS/DASH), conversión a H.264 "
                          "y captura de descargas del navegador.")

    def open_smart_detector(self):
        """Abre el detector inteligente de descargas"""
        try:
            clipboard_text = QApplication.clipboard().text().strip()
            if not (clipboard_text.startswith(('http://', 'https://')) or 'www.' in clipboard_text):
                clipboard_text = ""
            dialog = SmartDownloadDialog(self.manager, self, clipboard_text)
            if dialog.exec() == QDialog.Accepted:
                self.log_message("Detector inteligente completado")
                self.refresh_list()
        except Exception as e:
            self.logger.error(f"Error abriendo detector inteligente: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir el detector inteligente:\n{str(e)}")

    # ------------------------------------------------------------------
    # Inicio de descargas
    # ------------------------------------------------------------------

    def start_file_download(self, url, save_path, headers=None, cookies=None, start=True, batch=False):
        """Inicia (o deja en espera) una descarga directa multi-conexión. batch: una de muchas (sin ventanas)."""
        task_id = self.manager.add_download(
            url, save_path,
            threads=self.app_settings.get("default_threads"),
            speed_limit_kbps=max(0, self.app_settings.get("download_speed_limit_kbps")),
            headers=headers,
            cookies=cookies,
            start=start,
            max_retries=self.app_settings.get("auto_retry_count")
        )
        if batch:
            return task_id  # quien añade el lote avisa y refresca la lista una sola vez
        self.log_message(f"Nueva descarga {'añadida' if start else 'en espera'}: {os.path.basename(save_path)}")
        if start and self.app_settings.get("show_progress_dialog"):
            self.show_progress_dialog(task_id)
        self.refresh_list()
        return task_id

    def show_links_dialog(self, payload, context):
        """Descargar todos los enlaces de una página (desde la extensión): se eligen y van todos a la cola."""
        links = [link for link in payload.get("links") or []
                 if isinstance(link, dict) and str(link.get("url", "")).lower().startswith(("http://", "https://"))]
        if not links:
            self.log_message("La página no tiene enlaces para descargar")
            return
        dialog = LinksDialog(links, self.app_settings.get("default_download_folder"), payload.get("title") or "", self)
        self.bring_to_front(dialog)
        if dialog.exec() != QDialog.Accepted:
            return
        folder = dialog.folder()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Geas", f"No se pudo usar la carpeta:\n{e}")
            return
        used = set()  # nombres repetidos dentro del lote: los archivos aún no existen en el disco
        urls = dialog.selected_urls()
        for url in urls:
            path = unique_path(os.path.join(folder, sanitize_filename(filename_from_url(url, "descarga"))))
            base, ext = os.path.splitext(path)
            number = 1
            while path.lower() in used:
                path = f"{base} ({number}){ext}"
                number += 1
            used.add(path.lower())
            self.start_file_download(url, path, headers=context.http_headers(), cookies=context.cookie_jar(), batch=True)
        self.log_message(f"{len(urls)} enlaces añadidos a la cola desde {str(payload.get('url', ''))[:150]}")
        self.refresh_list()

    def show_video_quality_dialog(self, url, context=None, prefer_stream=False, from_browser=False, replace_entry=None):
        """Mostrar diálogo de selección de calidad"""
        try:
            convert = self.app_settings.get("convert_to_h264")
            dialog = VideoQualityDialog(url, self.manager, self, context=context, prefer_stream=prefer_stream,
                                        folder=self.app_settings.get("default_download_folder"),
                                        convert_note=bool(convert and find_ffmpeg()))
            if from_browser:
                self.bring_to_front(dialog)
            if dialog.exec() == QDialog.Accepted:
                info = dialog.get_download_info()
                # Descargar con las cookies/cabeceras con las que se analizó
                task_id = self.manager.add_yt_download(info['url'], info['save_path'], info['format_id'],
                                                       context=context, source=info.get('source'),
                                                       convert_h264=convert, start=info['start_now'])
                if replace_entry:
                    self.manager.remove_task(replace_entry)
                    self.manager.history.remove_entries([replace_entry])
                self.log_message(f"Iniciada descarga de video: {os.path.basename(info['save_path'])} "
                                 f"(formato {info['format_id']}, desde {info['url'][:150]})")
                if info['start_now'] and self.app_settings.get("show_progress_dialog"):
                    self.show_progress_dialog(task_id)
                self.refresh_list()

        except Exception as e:
            self.logger.error(f"Error en diálogo de video: {e}")
            QMessageBox.warning(self, "Error", f"Error al procesar video:\n{str(e)}")

    # ------------------------------------------------------------------
    # Solicitudes de la extensión del navegador
    # ------------------------------------------------------------------

    def bring_to_front(self, dialog):
        """Muestra el diálogo por encima del navegador (la solicitud llega con Geas en segundo plano)"""
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        QTimer.singleShot(0, dialog.raise_)
        QTimer.singleShot(0, dialog.activateWindow)

    def handle_browser_request(self, payload):
        """
        Atiende una descarga enviada por la extensión.
        kind: 'video'/'stream' -> diálogo de calidad (yt-dlp)
              'file'           -> descarga directa con las cookies del navegador
              'auto'           -> se consulta la URL y se decide
        """
        try:
            url = payload.get("url")
            kind = payload.get("kind", "auto")
            context = BrowserContext.from_payload(payload)
            self.log_message(f"Solicitud del navegador ({kind}): {url[:150]}")
            self.logger.info(f"Contexto del navegador: {context.summary()}")

            if self.address_dialog is not None and kind in ("file", "auto"):
                # "Actualizar dirección" está esperando el enlace nuevo: no es una descarga nueva
                self.address_dialog.capture(url, context)
                return

            if kind == "links":
                self.show_links_dialog(payload, context)
            elif kind in ("video", "stream"):
                self.show_video_quality_dialog(url, context=context, prefer_stream=(kind == "stream"), from_browser=True)
            elif kind == "file":
                self.start_browser_file_download(url, context, payload.get("filename"), payload.get("size"))
            else:
                self.probe_browser_link(url, context, payload.get("filename"))
        except Exception as e:
            self.logger.error(f"Error atendiendo solicitud del navegador: {e}")
            self.log_message(f"Error atendiendo solicitud del navegador: {e}")

    def probe_browser_link(self, url, context, filename=None, ask=False):
        """Consulta un enlace para saber si es una página (buscar video) o un archivo"""
        thread = UrlProbeThread(url, context.http_headers(), context.cookie_jar())
        # Mantener la referencia hasta que el hilo termine (si no, Qt lo destruiría en ejecución)
        self._probe_threads.add(thread)
        thread.finished.connect(lambda: self._probe_threads.discard(thread))
        self.status_label.setText("Consultando el enlace…")

        def on_probed(result):
            if not result.get("ok"):
                self.log_message(f"No se pudo consultar {url[:150]}: {result.get('error')}")
                QMessageBox.warning(self, "Geas", f"No se pudo acceder al enlace:\n{result.get('error')}")
                return

            content_type = result.get("content_type", "")
            if content_type in STREAM_CONTENT_TYPES:
                self.show_video_quality_dialog(url, context=context, prefer_stream=True, from_browser=not ask)
            elif content_type in ("text/html", "application/xhtml+xml"):
                # Es una página: buscar el video que contiene
                self.show_video_quality_dialog(url, context=context, from_browser=not ask)
            else:
                self.start_browser_file_download(url, context, filename or result.get("filename"),
                                                 result.get("size"), ask=ask)

        thread.probed.connect(on_probed)
        thread.start()

    def start_browser_file_download(self, url, context, filename=None, size=None, ask=False):
        """Descarga un archivo (con Referer, User-Agent y cookies del navegador si vienen de él)"""
        folder = self.app_settings.get("default_download_folder")
        name = sanitize_filename(filename or filename_from_url(url, "descarga"))
        save_path = unique_path(os.path.join(folder, name))
        start = True

        if ask or not self.app_settings.get("auto_start_downloads", True):
            dialog = FileInfoDialog(url, save_path, size, self)
            self.bring_to_front(dialog)
            if dialog.exec() != QDialog.Accepted:
                return
            save_path, start = dialog.save_path(), dialog.start_now

        self.start_file_download(url, save_path, headers=context.http_headers(), cookies=context.cookie_jar(),
                                 start=start)

    def on_browser_video_detected(self, url):
        """Manejar video detectado en el navegador integrado"""
        try:
            reply = QMessageBox.question(
                self, "Video detectado",
                f"Se detectó un video en esta página.\n¿Quieres analizarlo para descargar?\n\nURL: {url[:80]}…",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.show_video_quality_dialog(url)
        except Exception as e:
            self.logger.error(f"Error al procesar video detectado: {e}")

    # ------------------------------------------------------------------
    # Bandeja, portapapeles, registro y cierre
    # ------------------------------------------------------------------

    def setup_tray_icon(self):
        """Configurar icono de bandeja del sistema"""
        try:
            self.tray_icon = QSystemTrayIcon(icons.icon("app"), self)
            self.tray_icon.setToolTip("Geas")
            tray_menu = QMenu(self)
            show_action = QAction("Mostrar Geas", self)
            show_action.triggered.connect(self.show_window)
            tray_menu.addAction(show_action)
            tray_menu.addAction(self.act_add)
            tray_menu.addMenu(self.finish_menu)
            tray_menu.addSeparator()
            tray_menu.addAction(self.act_quit)
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self.on_tray_icon_activated)
            self.tray_icon.show()
        except Exception as e:
            self.logger.error(f"Error configurando bandeja: {e}")

    def notify(self, title, message):
        if self.app_settings.get("show_notifications") and getattr(self, "tray_icon", None) and self.tray_icon.isVisible():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.Information, 4000)

    def show_window(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.activateWindow()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_window()

    def force_quit(self):
        self._force_quit = True
        self.close()

    def closeEvent(self, event):
        """Limpiar recursos al cerrar la aplicación"""
        if (self.app_settings.get("minimize_to_tray", False) and not self._force_quit
                and getattr(self, "tray_icon", None) and self.tray_icon.isVisible()):
            self.hide()
            self.tray_icon.showMessage("Geas", "Geas sigue funcionando en segundo plano",
                                       QSystemTrayIcon.Information, 2000)
            event.ignore()
            return

        if not self._restarting:  # al reiniciar ya se preguntó y se detuvieron
            active = self._active_downloads()
            if active:
                reply = QMessageBox.question(
                    self, "Salir de Geas",
                    f"Hay {len(active)} descarga(s) en curso. Si sales, se detendrán y podrás reanudarlas "
                    f"desde donde quedaron al volver a abrir Geas.\n¿Salir?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply != QMessageBox.Yes:
                    self._force_quit = False
                    event.ignore()
                    return
            # Guarda el avance de cada descarga para continuarla al volver
            self.manager.shutdown()

        try:
            self.timer.stop()
            self.toggle_clipboard_monitor(False)
            for window in [*self.dialogs.values(), self.browser_window, self.scheduler_dialog, self.ytdlp_dialog,
                           self.log_window]:
                if window is not None:
                    window.close()
            if getattr(self, "tray_icon", None):
                self.tray_icon.hide()
        except Exception as e:
            self.logger.error(f"Error al cerrar la aplicación: {e}")
        event.accept()
        QApplication.instance().quit()

    def log_message(self, message):
        """Añadir mensaje al registro"""
        try:
            self.log_window.append(message)
            self.logger.info(message)
        except Exception as e:
            self.logger.error(f"Error añadiendo al log: {e}")

    def toggle_clipboard_monitor(self, enabled):
        """Activar/Desactivar monitor de portapapeles"""
        clipboard = QApplication.clipboard()
        if getattr(self, "_clipboard_connected", False):
            clipboard.dataChanged.disconnect(self.on_clipboard_change)
            self._clipboard_connected = False
        if enabled:
            self._last_clipboard_text = clipboard.text().strip()  # lo ya copiado no cuenta
            clipboard.dataChanged.connect(self.on_clipboard_change)
            self._clipboard_connected = True

    def on_clipboard_change(self):
        """Enlace copiado: videos -> calidad; archivos (zip, exe, mp4...) -> información del archivo"""
        text = QApplication.clipboard().text().strip()
        if not text or text == self._last_clipboard_text:
            return
        self._last_clipboard_text = text
        if not self.is_valid_url(text):
            return
        if self.is_video_url(text):
            self.show_video_quality_dialog(text, from_browser=True)
        elif category_of(urlparse(text).path)[0] != "General":
            self.probe_browser_link(text, BrowserContext(), ask=True)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def is_valid_url(self, url):
        """Validar que la URL sea válida"""
        pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        return bool(url) and pattern.match(url) is not None

    def is_video_url(self, url):
        """Detectar si la URL pertenece a un sitio de video conocido"""
        video_domains = [
            'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com',
            'facebook.com', 'instagram.com', 'tiktok.com', 'twitter.com', 'x.com',
            'twitch.tv'
        ]
        return any(domain in url.lower() for domain in video_domains)
