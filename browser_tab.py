import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, 
    QProgressBar, QLabel, QMessageBox
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
from PySide6.QtCore import QUrl, Signal, Qt

class NetworkInterceptor(QWebEngineUrlRequestInterceptor):
    """Intercepta peticiones de red para detectar medios y bloquear anuncios"""

    def __init__(self):
        super().__init__()
        self.known_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.mp3', '.m4a', '.wav']
        self.stream_extensions = ['.m3u8', '.mpd']
        self.ad_blocking_enabled = True
        
        # Lista básica de dominios de anuncios y trackers
        self.ad_domains = [
            "doubleclick.net", "googlesyndication.com", "googleadservices.com",
            "adnxs.com", "advertising.com", "rubiconproject.com", "criteo.com",
            "pubmatic.com", "openx.net", "ads-twitter.com", "facebook.com/tr/",
            "analytics", "tracker", "telemetry", "adsystem",
            "skinnycrawlinglax.com"
        ]

    def interceptRequest(self, info):
        url = info.requestUrl().toString()
        
        # 1. Bloqueo de Anuncios
        if self.ad_blocking_enabled:
            for domain in self.ad_domains:
                if domain in url:
                    print(f"Anuncio bloqueado: {url[:50]}...")
                    info.block(True)
                    return

        # 2. Detección de Medios
        # Detectar por extensión
        for ext in self.known_extensions:
            if url.lower().endswith(ext):
                print(f"Media detectado (ext): {url}")
                return

        # Detectar streams
        for ext in self.stream_extensions:
            if ext in url.lower():
                print(f"Stream detectado: {url}")
                return

class BrowserTab(QWidget):
    video_detected = Signal(str) # url

    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Barra de navegación
        nav_layout = QHBoxLayout()
        
        self.back_btn = QPushButton("⬅")
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.setFixedSize(30, 30)
        
        self.forward_btn = QPushButton("➡")
        self.forward_btn.clicked.connect(self.go_forward)
        self.forward_btn.setFixedSize(30, 30)
        
        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.clicked.connect(self.reload)
        self.refresh_btn.setFixedSize(30, 30)
        
        self.url_bar = QLineEdit()
        self.url_bar.returnPressed.connect(self.navigate_to_url)
        self.url_bar.setPlaceholderText("Escribe una URL (ej: youtube.com)")
        
        self.go_btn = QPushButton("Ir")
        self.go_btn.clicked.connect(self.navigate_to_url)
        
        # Botón de Bloqueo de Anuncios
        self.ad_block_btn = QPushButton("🛡️ ON")
        self.ad_block_btn.setCheckable(True)
        self.ad_block_btn.setChecked(True)
        self.ad_block_btn.clicked.connect(self.toggle_ad_block)
        self.ad_block_btn.setFixedWidth(60)
        self.ad_block_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        
        nav_layout.addWidget(self.back_btn)
        nav_layout.addWidget(self.forward_btn)
        nav_layout.addWidget(self.refresh_btn)
        nav_layout.addWidget(self.url_bar)
        nav_layout.addWidget(self.go_btn)
        nav_layout.addWidget(self.ad_block_btn)
        
        self.layout.addLayout(nav_layout)
        
        # Browser View
        self.browser = QWebEngineView()
        self.browser.urlChanged.connect(self.update_url_bar)
        self.browser.loadProgress.connect(self.update_progress)
        
        # Configurar Interceptor
        self.profile = QWebEngineProfile.defaultProfile()
        self.interceptor = NetworkInterceptor()
        self.profile.setUrlRequestInterceptor(self.interceptor)
        
        # Workaround: Usar evento de carga para inyectar JS que detecte video tags
        self.browser.loadFinished.connect(self.on_load_finished)

        self.layout.addWidget(self.browser)
        
        # Barra de progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        self.layout.addWidget(self.progress_bar)
        
        self.setLayout(self.layout)
        
        # Cargar página de inicio
        self.browser.setUrl(QUrl("https://www.google.com"))

    def toggle_ad_block(self):
        enabled = self.ad_block_btn.isChecked()
        self.interceptor.ad_blocking_enabled = enabled
        if enabled:
            self.ad_block_btn.setText("🛡️ ON")
            self.ad_block_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        else:
            self.ad_block_btn.setText("🛡️ OFF")
            self.ad_block_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.browser.reload()

    def navigate_to_url(self):
        url = self.url_bar.text().strip()
        if not url.startswith("http"):
            url = "https://" + url
        self.browser.setUrl(QUrl(url))

    def update_url_bar(self, q):
        self.url_bar.setText(q.toString())
        self.url_bar.setCursorPosition(0)

    def update_progress(self, p):
        self.progress_bar.setValue(p)
        if p == 100:
            self.progress_bar.hide()
        else:
            self.progress_bar.show()

    def go_back(self):
        self.browser.back()

    def go_forward(self):
        self.browser.forward()

    def reload(self):
        self.browser.reload()

    def on_load_finished(self):
        # Inyectar script para detectar videos HTML5
        js = """
        (function() {
            var videos = document.getElementsByTagName('video');
            if (videos.length > 0) {
                return videos[0].currentSrc || videos[0].src;
            }
            return "";
        })();
        """
        self.browser.page().runJavaScript(js, self.check_video_src)

    def check_video_src(self, src):
        if src:
            print(f"Video HTML5 detectado: {src}")
            # Emitir señal si es un video válido
            if src.startswith("http") and not src.startswith("blob:"):
                self.video_detected.emit(src)
            elif src.startswith("blob:"):
                # Blob URLs no se pueden descargar directamente con requests,
                # pero yt-dlp a veces puede manejar la URL de la página.
                # Así que emitimos la URL de la página actual.
                current_url = self.browser.url().toString()
                print(f"Blob detectado, usando URL de página: {current_url}")
                self.video_detected.emit(current_url)
