# smart_download_dialog.py - Diálogo Inteligente de Descarga

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QProgressBar, QTextEdit, QTabWidget, QWidget,
    QSpinBox, QCheckBox, QGroupBox, QSplitter, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap
import sys
import os
from url_detector import UniversalDownloadDetector
from enhanced_downloader import EnhancedDownloadTask
import threading
import time

class UrlAnalysisThread(QThread):
    """Hilo para analizar URLs sin bloquear la UI"""
    analysis_complete = Signal(list)  # Lista de archivos encontrados
    analysis_error = Signal(str)      # Error en el análisis
    progress_update = Signal(str)     # Actualización de progreso
    
    def __init__(self, url_text):
        super().__init__()
        self.url_text = url_text
        self.detector = UniversalDownloadDetector()
    
    def run(self):
        try:
            self.progress_update.emit("Analizando URL...")
            results = self.detector.smart_detect(self.url_text)
            self.analysis_complete.emit(results)
        except Exception as e:
            self.analysis_error.emit(str(e))

class SmartDownloadDialog(QDialog):
    """Diálogo inteligente que detecta automáticamente archivos descargables"""
    
    def __init__(self, manager, parent=None, initial_url=""):
        super().__init__(parent)
        self.manager = manager
        self.detector = UniversalDownloadDetector()
        self.found_files = []
        
        self.setWindowTitle("Detector Inteligente de Descargas")
        self.setGeometry(200, 200, 900, 700)
        self.setModal(True)
        
        # Variables para descarga
        self.active_downloads = {}
        
        self.setup_ui()
        
        # Si se proporcionó URL inicial, analizarla
        if initial_url:
            self.url_input.setText(initial_url)
            self.analyze_url()
    
    def setup_ui(self):
        """Configura la interfaz de usuario"""
        layout = QVBoxLayout()
        
        # === Sección de entrada de URL ===
        url_group = QGroupBox("🔍 Análisis de URL")
        url_layout = QVBoxLayout()
        
        # Input de URL
        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Pega aquí la URL de la página o archivo...")
        self.url_input.returnPressed.connect(self.analyze_url)
        
        self.analyze_btn = QPushButton("🔍 Analizar")
        self.analyze_btn.clicked.connect(self.analyze_url)
        
        self.paste_btn = QPushButton("📋 Pegar")
        self.paste_btn.clicked.connect(self.paste_from_clipboard)
        
        input_layout.addWidget(QLabel("URL:"))
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(self.paste_btn)
        input_layout.addWidget(self.analyze_btn)
        
        url_layout.addLayout(input_layout)
        
        # Barra de progreso del análisis
        self.analysis_progress = QProgressBar()
        self.analysis_progress.setVisible(False)
        url_layout.addWidget(self.analysis_progress)
        
        # Label de estado
        self.status_label = QLabel("Introduce una URL para comenzar el análisis")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        url_layout.addWidget(self.status_label)
        
        url_group.setLayout(url_layout)
        layout.addWidget(url_group)
        
        # === Sección de resultados ===
        results_group = QGroupBox("📁 Archivos Detectados")
        results_layout = QVBoxLayout()
        
        # Tabla de archivos encontrados
        self.files_table = QTableWidget()
        self.files_table.setColumnCount(7)
        self.files_table.setHorizontalHeaderLabels([
            "✓", "Nombre", "Tamaño", "Tipo", "URL", "Origen", "Reanudable"
        ])
        
        # Configurar tabla
        header = self.files_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # Checkbox
        header.setSectionResizeMode(1, QHeaderView.Stretch) # Nombre
        header.setSectionResizeMode(2, QHeaderView.Fixed)   # Tamaño
        header.setSectionResizeMode(3, QHeaderView.Fixed)   # Tipo
        header.setSectionResizeMode(4, QHeaderView.Stretch) # URL
        header.setSectionResizeMode(5, QHeaderView.Fixed)   # Origen
        header.setSectionResizeMode(6, QHeaderView.Fixed)   # Reanudable
        
        self.files_table.resizeColumnToContents(0)
        self.files_table.setColumnWidth(0, 30)
        self.files_table.setColumnWidth(2, 80)
        self.files_table.setColumnWidth(3, 100)
        self.files_table.setColumnWidth(5, 120)
        self.files_table.setColumnWidth(6, 80)
        
        # Permitir selección múltiple
        self.files_table.setSelectionBehavior(QTableWidget.SelectRows)
        
        results_layout.addWidget(self.files_table)
        
        # Botones de selección
        selection_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("✓ Seleccionar Todo")
        self.select_all_btn.clicked.connect(self.select_all_files)
        
        self.select_none_btn = QPushButton("✗ Deseleccionar Todo")
        self.select_none_btn.clicked.connect(self.select_no_files)
        
        self.select_videos_btn = QPushButton("🎥 Solo Videos")
        self.select_videos_btn.clicked.connect(self.select_videos_only)
        
        selection_layout.addWidget(self.select_all_btn)
        selection_layout.addWidget(self.select_none_btn)
        selection_layout.addWidget(self.select_videos_btn)
        selection_layout.addStretch()
        
        results_layout.addLayout(selection_layout)
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
        
        # === Sección de configuración ===
        config_group = QGroupBox("⚙️ Configuración de Descarga")
        config_layout = QHBoxLayout()
        
        # Número de hilos
        config_layout.addWidget(QLabel("Hilos:"))
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 32)
        self.threads_spin.setValue(4)
        config_layout.addWidget(self.threads_spin)
        
        # Límite de velocidad
        config_layout.addWidget(QLabel("Límite (KB/s):"))
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(0, 102400)
        self.speed_spin.setValue(0)
        self.speed_spin.setSpecialValueText("Sin límite")
        config_layout.addWidget(self.speed_spin)
        
        # Verificar integridad
        self.verify_integrity_cb = QCheckBox("Verificar integridad")
        config_layout.addWidget(self.verify_integrity_cb)
        
        config_layout.addStretch()
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # === Botones principales ===
        buttons_layout = QHBoxLayout()
        
        self.download_btn = QPushButton("⬇️ Descargar Seleccionados")
        self.download_btn.clicked.connect(self.start_downloads)
        self.download_btn.setEnabled(False)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 16px;
                font-weight: bold;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        
        self.close_btn = QPushButton("❌ Cerrar")
        self.close_btn.clicked.connect(self.reject)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.download_btn)
        buttons_layout.addWidget(self.close_btn)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
        
        # Configurar estilos
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QTableWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: white;
            }
            QTableWidget::item:selected {
                background-color: #3daee9;
                color: white;
            }
        """)
    
    def paste_from_clipboard(self):
        """Pega contenido del portapapeles"""
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            self.url_input.setText(text)
    
    def analyze_url(self):
        """Inicia el análisis de la URL"""
        url_text = self.url_input.text().strip()
        if not url_text:
            QMessageBox.warning(self, "Error", "Por favor introduce una URL")
            return
        
        # Mostrar progreso
        self.analysis_progress.setVisible(True)
        self.analysis_progress.setRange(0, 0)  # Indeterminado
        self.status_label.setText("Analizando...")
        self.analyze_btn.setEnabled(False)
        
        # Limpiar tabla anterior
        self.files_table.setRowCount(0)
        self.found_files.clear()
        
        # Ejecutar análisis en hilo separado
        self.analysis_thread = UrlAnalysisThread(url_text)
        self.analysis_thread.analysis_complete.connect(self.on_analysis_complete)
        self.analysis_thread.analysis_error.connect(self.on_analysis_error)
        self.analysis_thread.progress_update.connect(self.on_progress_update)
        self.analysis_thread.start()
    
    def on_progress_update(self, message):
        """Actualiza el mensaje de progreso"""
        self.status_label.setText(message)
    
    def on_analysis_complete(self, results):
        """Maneja la finalización del análisis"""
        self.analysis_progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        
        if not results:
            self.status_label.setText("No se encontraron archivos descargables")
            return
        
        self.found_files = results
        self.populate_files_table(results)
        self.status_label.setText(f"Se encontraron {len(results)} archivo(s) descargable(s)")
        self.download_btn.setEnabled(True)
    
    def on_analysis_error(self, error_message):
        """Maneja errores en el análisis"""
        self.analysis_progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.status_label.setText(f"Error en análisis: {error_message}")
        QMessageBox.critical(self, "Error", f"Error analizando URL:\n{error_message}")
    
    def populate_files_table(self, files):
        """Puebla la tabla con los archivos encontrados"""
        self.files_table.setRowCount(len(files))
        
        for row, file_info in enumerate(files):
            # Checkbox para selección
            checkbox = QCheckBox()
            checkbox.setChecked(True)  # Seleccionado por defecto
            self.files_table.setCellWidget(row, 0, checkbox)
            
            # Nombre del archivo
            filename = file_info.get('filename', 'Archivo sin nombre')
            self.files_table.setItem(row, 1, QTableWidgetItem(filename))
            
            # Tamaño
            size = file_info.get('size', 0)
            size_text = self.detector.format_size(size) if size > 0 else "Desconocido"
            self.files_table.setItem(row, 2, QTableWidgetItem(size_text))
            
            # Tipo de contenido
            content_type = file_info.get('content_type', 'Desconocido')
            if '/' in content_type:
                content_type = content_type.split('/')[0].title()
            self.files_table.setItem(row, 3, QTableWidgetItem(content_type))
            
            # URL (truncada para display)
            url = file_info.get('url', '')
            display_url = url[:50] + "..." if len(url) > 50 else url
            url_item = QTableWidgetItem(display_url)
            url_item.setToolTip(url)  # URL completa en tooltip
            self.files_table.setItem(row, 4, url_item)
            
            # Tipo de detección
            detection_type = file_info.get('detection_type', 'unknown')
            type_map = {
                'direct_file': 'Directo',
                'page_scan': 'Página',
                'unknown': 'Desconocido'
            }
            self.files_table.setItem(row, 5, QTableWidgetItem(type_map.get(detection_type, 'Otro')))
            
            # Soporte de reanudación
            supports_resume = file_info.get('supports_resume', False)
            resume_text = "Sí" if supports_resume else "No"
            self.files_table.setItem(row, 6, QTableWidgetItem(resume_text))
    
    def select_all_files(self):
        """Selecciona todos los archivos"""
        for row in range(self.files_table.rowCount()):
            checkbox = self.files_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(True)
    
    def select_no_files(self):
        """Deselecciona todos los archivos"""
        for row in range(self.files_table.rowCount()):
            checkbox = self.files_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(False)
    
    def select_videos_only(self):
        """Selecciona solo archivos de video"""
        video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v'}
        
        for row in range(self.files_table.rowCount()):
            checkbox = self.files_table.cellWidget(row, 0)
            if checkbox and row < len(self.found_files):
                filename = self.found_files[row].get('filename', '')
                is_video = any(filename.lower().endswith(ext) for ext in video_extensions)
                checkbox.setChecked(is_video)
    
    def get_selected_files(self):
        """Obtiene los archivos seleccionados"""
        selected = []
        for row in range(self.files_table.rowCount()):
            checkbox = self.files_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked() and row < len(self.found_files):
                selected.append(self.found_files[row])
        return selected
    
    def start_downloads(self):
        """Inicia las descargas seleccionadas"""
        selected_files = self.get_selected_files()
        
        if not selected_files:
            QMessageBox.warning(self, "Error", "No hay archivos seleccionados")
            return
        
        # Obtener configuración
        threads = self.threads_spin.value()
        speed_limit = self.speed_spin.value()
        
        successful_downloads = 0
        
        for file_info in selected_files:
            try:
                # Usar el enhanced downloader
                url = file_info['url']
                filename = file_info['filename']
                
                # Obtener carpeta de descarga de configuración
                from settings import AppSettings
                settings = AppSettings()
                download_folder = settings.get("default_download_folder")
                output_path = os.path.join(download_folder, filename)
                
                # Crear descarga usando el manager existente
                task_id = self.manager.add_download(
                    url, 
                    output_path, 
                    threads=threads, 
                    speed_limit_kbps=speed_limit if speed_limit > 0 else 0
                )
                
                successful_downloads += 1
                
            except Exception as e:
                QMessageBox.warning(
                    self, "Error", 
                    f"Error iniciando descarga de {file_info['filename']}:\n{str(e)}"
                )
        
        if successful_downloads > 0:
            QMessageBox.information(
                self, "Éxito", 
                f"Se iniciaron {successful_downloads} descarga(s) exitosamente"
            )
            self.accept()  # Cerrar diálogo
        else:
            QMessageBox.critical(self, "Error", "No se pudo iniciar ninguna descarga")


if __name__ == "__main__":
    # Test standalone del diálogo
    app = QApplication(sys.argv)
    
    # Mock manager para testing
    class MockManager:
        def add_download(self, url, output_path, threads=4, speed_limit_kbps=0):
            print(f"Mock descarga: {url} -> {output_path}")
            return "mock_task_id"
    
    dialog = SmartDownloadDialog(MockManager())
    dialog.show()
    sys.exit(app.exec())