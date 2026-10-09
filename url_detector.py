# url_detector.py - Detector Universal de URLs de Descarga

import requests
import re
import urllib.parse
from bs4 import BeautifulSoup
import mimetypes
from typing import List, Dict, Optional, Tuple
import json
import os
from urllib.parse import urljoin, urlparse, parse_qs
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class UniversalDownloadDetector:
    """
    Detector universal que puede encontrar enlaces de descarga en cualquier página web
    Similar a como lo hace Internet Download Manager
    """
    
    def __init__(self):
        self.session = requests.Session()
        self._setup_session()
        self.downloadable_extensions = {
            # Videos
            '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp',
            # Audio
            '.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a',
            # Archivos
            '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz',
            # Documentos
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
            # Imagenes
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.tiff', '.webp',
            # Programas
            '.exe', '.msi', '.dmg', '.pkg', '.deb', '.rpm', '.appimage',
            # Otros
            '.iso', '.img', '.bin', '.torrent', '.apk', '.ipa'
        }
        
        # Patrones para detectar enlaces de descarga
        self.download_patterns = [
            r'href=[\'"](.*?download.*?)[\'"]',
            r'href=[\'"](.*?\.(?:' + '|'.join([ext[1:] for ext in self.downloadable_extensions]) + r'))[\'"]',
            r'onclick=[\'"].*?(?:location\.href|window\.open)\s*=\s*[\'"](.*?)[\'"]',
            r'data-download-url=[\'"](.*?)[\'"]',
            r'data-url=[\'"](.*?)[\'"]'
        ]
        
        # Headers específicos por sitio
        self.site_headers = {
            'youtube.com': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            },
            'mediafire.com': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.mediafire.com/'
            },
            'mega.nz': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            },
            'default': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
        }

    def _setup_session(self):
        """Configura la sesión con reintentos y timeouts"""
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
    def get_site_headers(self, url: str) -> Dict[str, str]:
        """Obtiene headers específicos para el sitio"""
        domain = urlparse(url).netloc.lower()
        
        for site, headers in self.site_headers.items():
            if site in domain:
                return headers
                
        return self.site_headers['default']

    def is_downloadable_url(self, url: str) -> bool:
        """Verifica si una URL apunta a un archivo descargable"""
        try:
            parsed = urlparse(url)
            path = parsed.path.lower()
            
            # Verificar extensión
            for ext in self.downloadable_extensions:
                if path.endswith(ext):
                    return True
                    
            # Verificar patrones en query parameters
            if any(keyword in url.lower() for keyword in ['download', 'file', 'attachment']):
                return True
                
            return False
        except:
            return False

    def extract_filename_from_url(self, url: str, headers: Dict = None) -> str:
        """Extrae el nombre del archivo de la URL o headers"""
        try:
            # Intentar desde Content-Disposition header
            if headers and 'content-disposition' in headers:
                content_disp = headers['content-disposition']
                filename_match = re.search(r'filename[*]?=[\'"]?([^\'"]+)', content_disp)
                if filename_match:
                    return filename_match.group(1).strip('\'"')
            
            # Desde la URL
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path)
            
            if filename and '.' in filename:
                return filename
                
            # Si no hay nombre, usar timestamp
            return f"archivo_{int(time.time())}"
            
        except:
            return f"archivo_{int(time.time())}"

    def get_file_info(self, url: str) -> Optional[Dict[str, any]]:
        """Obtiene información del archivo sin descargarlo completamente"""
        try:
            headers = self.get_site_headers(url)
            
            # HEAD request para obtener metadata
            response = self.session.head(url, headers=headers, timeout=10, allow_redirects=True)
            
            if response.status_code == 405:  # Método HEAD no permitido
                # Intentar GET con Range para obtener solo headers
                headers['Range'] = 'bytes=0-0'
                response = self.session.get(url, headers=headers, timeout=10, stream=True)
                response.close()  # Cerrar inmediatamente
            
            if response.status_code not in [200, 206, 416]:  # 416 = Range Not Satisfiable (OK para nuestro propósito)
                return None
                
            file_info = {
                'url': response.url,  # URL final después de redirects
                'filename': self.extract_filename_from_url(response.url, response.headers),
                'size': int(response.headers.get('content-length', 0)),
                'content_type': response.headers.get('content-type', ''),
                'supports_resume': 'accept-ranges' in response.headers,
                'headers': dict(response.headers)
            }
            
            return file_info
            
        except Exception as e:
            print(f"Error obteniendo info del archivo {url}: {e}")
            return None

    def find_download_links(self, page_url: str) -> List[Dict[str, any]]:
        """Encuentra todos los enlaces de descarga en una página"""
        try:
            headers = self.get_site_headers(page_url)
            response = self.session.get(page_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            found_links = []
            
            # Buscar enlaces directos
            for link in soup.find_all('a', href=True):
                href = link['href']
                absolute_url = urljoin(page_url, href)
                
                if self.is_downloadable_url(absolute_url):
                    link_text = link.get_text(strip=True)
                    file_info = self.get_file_info(absolute_url)
                    
                    if file_info:
                        file_info['link_text'] = link_text
                        file_info['source_page'] = page_url
                        found_links.append(file_info)
            
            # Buscar enlaces en JavaScript
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    for pattern in self.download_patterns:
                        matches = re.findall(pattern, script.string, re.IGNORECASE)
                        for match in matches:
                            absolute_url = urljoin(page_url, match)
                            if self.is_downloadable_url(absolute_url):
                                file_info = self.get_file_info(absolute_url)
                                if file_info:
                                    file_info['link_text'] = 'JavaScript Link'
                                    file_info['source_page'] = page_url
                                    found_links.append(file_info)
            
            # Buscar en data attributes
            for element in soup.find_all(attrs={'data-download-url': True}):
                url = element['data-download-url']
                absolute_url = urljoin(page_url, url)
                file_info = self.get_file_info(absolute_url)
                if file_info:
                    file_info['link_text'] = element.get_text(strip=True) or 'Data Attribute'
                    file_info['source_page'] = page_url
                    found_links.append(file_info)
            
            # Eliminar duplicados
            unique_links = []
            seen_urls = set()
            for link in found_links:
                if link['url'] not in seen_urls:
                    unique_links.append(link)
                    seen_urls.add(link['url'])
            
            return unique_links
            
        except Exception as e:
            print(f"Error buscando enlaces en {page_url}: {e}")
            return []

    def smart_detect(self, url_or_text: str) -> List[Dict[str, any]]:
        """
        Detección inteligente: 
        - Si es URL directa a archivo, la analiza
        - Si es página web, busca enlaces de descarga
        - Si es texto con URLs, las extrae y analiza
        """
        results = []
        
        # Extraer URLs del texto
        url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+|[^\s<>"\'/]+\.[a-z]{2,}(?:/[^\s<>"\']*)?'
        urls = re.findall(url_pattern, url_or_text, re.IGNORECASE)
        
        if not urls:
            # Si no encuentra URLs, tratar como URL directa
            urls = [url_or_text]
        
        for url in urls:
            # Asegurar protocolo
            if not url.startswith(('http://', 'https://')):
                if url.startswith('www.'):
                    url = 'https://' + url
                else:
                    url = 'https://' + url
            
            try:
                # ¿Es archivo descargable directo?
                if self.is_downloadable_url(url):
                    file_info = self.get_file_info(url)
                    if file_info:
                        file_info['detection_type'] = 'direct_file'
                        results.append(file_info)
                else:
                    # Buscar enlaces en la página
                    page_links = self.find_download_links(url)
                    for link in page_links:
                        link['detection_type'] = 'page_scan'
                        results.append(link)
                        
            except Exception as e:
                print(f"Error procesando {url}: {e}")
                continue
        
        return results

    def format_size(self, size_bytes: int) -> str:
        """Formatea el tamaño en bytes a formato legible"""
        if size_bytes == 0:
            return "Desconocido"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"


# Función de utilidad para usar desde otros módulos
def detect_downloads(url_or_text: str) -> List[Dict[str, any]]:
    """Función de conveniencia para detección rápida"""
    detector = UniversalDownloadDetector()
    return detector.smart_detect(url_or_text)


if __name__ == "__main__":
    # Test del detector
    detector = UniversalDownloadDetector()
    
    test_urls = [
        "https://www.python.org/ftp/python/3.9.7/python-3.9.7-amd64.exe",
        "https://github.com/",
        "https://www.mediafire.com/"
    ]
    
    for test_url in test_urls:
        print(f"\n=== Analizando: {test_url} ===")
        results = detector.smart_detect(test_url)
        
        if results:
            for i, result in enumerate(results, 1):
                print(f"{i}. {result['filename']}")
                print(f"   URL: {result['url']}")
                print(f"   Tamaño: {detector.format_size(result['size'])}")
                print(f"   Tipo: {result['content_type']}")
                print(f"   Reanudable: {'Sí' if result['supports_resume'] else 'No'}")
        else:
            print("No se encontraron archivos descargables")