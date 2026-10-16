# enhanced_downloader.py - Downloader Mejorado Similar a IDM

import requests
import ctypes
import os
import re
import sys
import threading
import time
import hashlib
from typing import Optional, Dict, Callable
from urllib.parse import urlparse, unquote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import network
from browser_context import DEFAULT_USER_AGENT

_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}

PART_SUFFIX = ".part"          # se descarga en "nombre.ext.part" y se renombra al terminar
MIN_PART_SIZE = 256 * 1024     # tramo inicial mínimo por conexión
MIN_SPLIT_SIZE = 512 * 1024    # una conexión libre solo parte tramos con al menos el doble pendiente
STATE_SAVE_INTERVAL = 2.0      # segundos entre guardados del avance (para reanudar tras cerrar)
MAX_CONNECTION_FAILURES = 3    # fallos seguidos con los que una conexión se retira (siguen las demás)


class DownloadError(Exception):
    """Error de descarga; retryable indica si tiene sentido reintentar."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class RangeNotSupported(Exception):
    """El servidor ignoró la cabecera Range: no se puede descargar por partes."""


def sanitize_filename(name: str, default: str = "descarga") -> str:
    """Deja un nombre de archivo válido en Windows y sin rutas."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        return default
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        name = "_" + name
    if len(name) > 200:
        stem, ext = os.path.splitext(name)
        name = stem[:200 - len(ext)] + ext
    return name


def _taken(path: str) -> bool:
    # También cuenta el .part de una descarga sin terminar: si no, la nueva lo pisaría
    return os.path.exists(path) or os.path.exists(path + PART_SUFFIX)


def unique_path(path: str) -> str:
    """Si el archivo ya existe agrega ' (1)', ' (2)', ... como hace el navegador."""
    if not _taken(path):
        return path
    stem, ext = os.path.splitext(path)
    counter = 1
    while _taken(f"{stem} ({counter}){ext}"):
        counter += 1
    return f"{stem} ({counter}){ext}"


def filename_from_url(url: str, default: str = "") -> str:
    name = unquote(os.path.basename(urlparse(url).path))
    return sanitize_filename(name, default) if name else default


def filename_from_headers(headers, url: str) -> str:
    """Nombre desde Content-Disposition (incluido filename*=UTF-8''...) o, si no hay, desde la URL."""
    content_disp = headers.get('content-disposition', '') if headers else ''
    match = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", content_disp, re.IGNORECASE)
    if match:
        try:
            return sanitize_filename(unquote(match.group(2).strip().strip('"'), encoding=match.group(1) or 'utf-8'))
        except LookupError:
            pass
    match = (re.search(r'filename\s*=\s*"([^"]+)"', content_disp, re.IGNORECASE)
             or re.search(r"filename\s*=\s*([^;]+)", content_disp, re.IGNORECASE))
    if match:
        return sanitize_filename(match.group(1).strip().strip('"\''))
    return filename_from_url(url)


def probe(session: requests.Session, url: str, timeout: int = 30) -> Dict:
    """
    Consulta el recurso sin descargarlo: URL final, tamaño, tipo, nombre y si
    admite rangos. Usa HEAD y, si el servidor no lo admite (p. ej. URLs firmadas
    solo para GET) o no informa el tamaño, un GET de 1 byte con Range.
    """
    try:
        response = session.head(url, allow_redirects=True, timeout=timeout)
    except requests.RequestException:
        response = None

    if response is None or not response.ok or not response.headers.get('content-length'):
        response = session.get(url, headers={'Range': 'bytes=0-0'}, stream=True,
                               allow_redirects=True, timeout=timeout)
        response.close()
    response.raise_for_status()

    headers = response.headers
    size = 0
    accepts_ranges = headers.get('accept-ranges', '').lower() == 'bytes'
    if response.status_code == 206:
        accepts_ranges = True
        total = headers.get('content-range', '').rsplit('/', 1)[-1].strip()
        size = int(total) if total.isdigit() else 0
    elif headers.get('content-length', '').isdigit():
        size = int(headers['content-length'])

    return {
        'final_url': response.url,
        'size': size,
        'accepts_ranges': accepts_ranges,
        'content_type': headers.get('content-type', '').split(';')[0].strip().lower(),
        'filename': filename_from_headers(headers, response.url),
        # Para saber, al reanudar, si el archivo del servidor sigue siendo el mismo
        'etag': headers.get('etag'),
        'last_modified': headers.get('last-modified'),
    }


def url_probe(url: str, headers: Dict = None, cookies=None, timeout: int = 15) -> Dict:
    """probe() con una sesión nueva. Devuelve {'ok': True, ...} o {'ok': False, 'error': ...}."""
    session = requests.Session()
    session.headers.update({'User-Agent': DEFAULT_USER_AGENT, 'Accept-Encoding': 'identity'})
    session.headers.update(headers or {})
    session.auth = network.login_for(url)  # usuario y contraseña guardados para ese sitio
    if cookies:
        session.cookies.update(cookies)
    try:
        return {'ok': True, **probe(session, url, timeout=timeout)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    finally:
        session.close()


if sys.platform == "win32":
    import msvcrt
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                          wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                          wintypes.LPVOID]
    _kernel32.DeviceIoControl.restype = wintypes.BOOL
    _kernel32.SetEndOfFile.argtypes = [wintypes.HANDLE]
    _kernel32.SetEndOfFile.restype = wintypes.BOOL
    _FSCTL_SET_SPARSE = 0x000900C4


def _reserve_size(f, size: int):
    """
    Deja el .part con su tamaño final al instante, sin escribir ceros.

    En Windows, truncate() agranda el archivo ESCRIBIENDO ceros (lo hace el CRT), y
    SetEndOfFile a secas solo lo aplaza: NTFS rellena con ceros hasta donde escribe la
    conexión que empieza más lejos. En un disco duro, 1 GiB eran ~9 s sin recibir nada
    (medido el 16-oct). Un archivo disperso no se rellena: el espacio se ocupa a medida
    que llegan los datos. Si el sistema de archivos no lo admite (FAT32, exFAT, algunas
    unidades de red), se reserva como siempre.
    """
    if sys.platform == "win32":
        handle = msvcrt.get_osfhandle(f.fileno())
        done = wintypes.DWORD()
        if _kernel32.DeviceIoControl(handle, _FSCTL_SET_SPARSE, None, 0, None, 0, ctypes.byref(done), None):
            f.seek(size)
            if _kernel32.SetEndOfFile(handle):
                return
    f.truncate(size)


def _write_all(f, data):
    """Escribe todo el bloque (sin búfer, write() puede escribir menos de lo pedido)."""
    view = memoryview(data)
    while view:
        view = view[f.write(view):]


class EnhancedDownloadTask:
    """
    Descarga multi-conexión con segmentación dinámica, como IDM: el archivo se
    reparte en tramos y, cuando una conexión termina el suyo, parte en dos el
    tramo al que más le falta y se queda con la segunda mitad. Así ninguna
    conexión queda ociosa mientras otra, más lenta, carga con el final.

    Se descarga en "<archivo>.part" y se renombra al terminar. snapshot()
    devuelve el avance (tramos y bytes de cada uno); pasado como resume_state,
    otra tarea continúa desde ahí aunque Geas se haya cerrado, si el archivo
    del servidor no cambió.
    """

    def __init__(self, url: str, output_path: str, threads: int = 4,
                 speed_limit_kbps: int = 0, headers: Dict = None,
                 progress_callback: Callable = None, cookies=None, max_retries: int = 3,
                 resume_state: Dict = None, state_callback: Callable = None):
        self.url = url
        self.output_path = output_path
        self.part_path = output_path + PART_SUFFIX
        self.threads = max(1, threads or 1)
        self.speed_limit_kbps = speed_limit_kbps if speed_limit_kbps is not None else 0
        self.chunk_size = 64 * 1024
        self.progress_callback = progress_callback
        self.resume_state = resume_state      # avance guardado en una sesión anterior
        self.state_callback = state_callback  # recibe snapshot() cada pocos segundos

        # Estados y control
        self.pause_flag = threading.Event()
        self.cancel_flag = threading.Event()
        self.progress = 0
        self.total_size = 0
        self.status = "esperando"
        self.thread_list = []
        self.download_speed = 0
        self.start_time = None
        self.eta = 0

        # Configuración avanzada
        self.custom_headers = headers or {}
        self.cookies = cookies  # CookieJar con las cookies del navegador
        self.session = requests.Session()
        # Usuario y contraseña guardados para ese sitio (requests no los manda si redirige a otro servidor)
        self.session.auth = network.login_for(url)
        self.retry_count = 0
        self.max_retries = max_retries
        self.resumable = False  # el servidor acepta rangos (descarga por partes / reanudable)
        self._etag = None
        self._last_modified = None

        # Tramos del archivo {start, end, downloaded, inflight, owner, state} (barra de la ventana de progreso)
        self.segments = []
        # Una entrada por conexión {downloaded, state} (tabla "Conexiones de descarga")
        self.connections = []
        self._speed_time = None
        self._speed_bytes = 0
        self._last_state_save = 0.0
        self._last_error = None

        # Para verificación de integridad
        self.expected_hash = None
        self.hash_algorithm = 'md5'

        # Sincronización entre hilos de descarga
        self._lock = threading.Lock()
        self._abort_flag = threading.Event()  # error definitivo en una conexión: las demás se detienen
        self._thread_errors = []

        self._setup_session()

    def _setup_session(self):
        """Configura la sesión con reintentos y headers apropiados"""
        # Configurar reintentos automáticos
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        # Una conexión reutilizable por hilo de descarga
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_maxsize=max(10, self.threads + 2))
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Headers por defecto más robustos
        default_headers = {
            'User-Agent': DEFAULT_USER_AGENT,
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            # Sin compresión: los rangos y el tamaño deben corresponder a los bytes reales del archivo
            'Accept-Encoding': 'identity',
            'Connection': 'keep-alive',
        }

        # Mergear con headers personalizados (Referer, User-Agent del navegador, ...)
        default_headers.update(self.custom_headers)
        self.session.headers.update(default_headers)
        if self.cookies:
            self.session.cookies.update(self.cookies)

    def get_file_info(self) -> bool:
        """Obtiene información del archivo antes de descargarlo"""
        try:
            self._apply_file_info(probe(self.session, self.url))
            return True
        except Exception as e:
            print(f"Error obteniendo información del archivo: {e}")
            self.status = f"error: {e}"
            return False

    def _apply_file_info(self, info: Dict):
        """Guarda URL final, tamaño, soporte de rangos y nombre obtenidos con probe()"""
        # Actualizar URL final (después de redirects)
        self.url = info['final_url']
        self.total_size = info['size']
        # Por partes (y reanudable) solo si admite rangos y se conoce el tamaño
        self.resumable = info['accepts_ranges'] and info['size'] > 0

        # Verificar si soporta rangos (para descarga multi-hilo)
        if not info['accepts_ranges'] and self.threads > 1:
            print("El servidor no soporta rangos, usando descarga de un solo hilo")
            self.threads = 1

        # Extraer filename si no se especificó
        if not os.path.basename(self.output_path):
            filename = info['filename'] or f"archivo_{int(time.time())}"
            self.output_path = os.path.join(self.output_path, filename)
        self.part_path = self.output_path + PART_SUFFIX

    def run(self):
        """Ejecuta la descarga, con reintentos automáticos (cada reintento sigue donde quedó el anterior)"""
        while True:
            try:
                self._run_attempt()
                if self.cancel_flag.is_set():
                    self._save_state(force=True)
                return
            except Exception as e:
                if self.cancel_flag.is_set():
                    self.status = "cancelado"
                    self._save_state(force=True)
                    return
                print(f"Error en descarga: {e}")
                self.status = f"error: {e}"
                self._save_state(force=True)

                # Reintentar si es apropiado
                if not self._is_retryable(e) or self.retry_count >= self.max_retries:
                    return
                self.retry_count += 1
                print(f"Reintentando descarga ({self.retry_count}/{self.max_retries})")
                if self.cancel_flag.wait(2 ** self.retry_count):  # Backoff exponencial (atento a Cancelar)
                    self.status = "cancelado"
                    return

    def _run_attempt(self):
        """Un intento completo de descarga (información + datos + verificación)"""
        # Avance de un intento anterior de esta sesión o, en el primero, de una sesión anterior
        previous = self.snapshot() or self.resume_state
        self.status = "obteniendo información"
        self.start_time = time.time()
        self.download_speed = 0
        self.thread_list = []
        self._thread_errors = []
        self._last_error = None
        self._abort_flag.clear()

        # Obtener información del archivo
        info = probe(self.session, self.url)
        self._apply_file_info(info)
        self._etag, self._last_modified = info.get('etag'), info.get('last_modified')

        # Crear directorio si no existe y verificar espacio en disco
        os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
        restored = self._restore_segments(previous, info)
        self.resume_state = None  # ya se usó (o no servía); los reintentos siguen con snapshot()
        if not restored and not self._check_disk_space():
            raise DownloadError("espacio insuficiente en disco", retryable=False)
        self._speed_time, self._speed_bytes = time.time(), self.progress

        self.status = "descargando"
        if self.resumable:
            if not restored:
                self._create_segments()
            if not self._multi_connection_download():
                # El servidor ignoró los rangos: empezar de nuevo con una sola conexión
                self.resumable = False
                self.threads = 1
                self._single_stream_download()
        else:
            self._single_stream_download()

        if self.cancel_flag.is_set():
            self.status = "cancelado"
            return

        if self.total_size and self.progress < self.total_size:
            raise DownloadError("descarga incompleta")

        # Verificar integridad si se especificó
        if self.expected_hash and not self._verify_integrity():
            raise DownloadError("verificación de integridad fallida", retryable=False)

        self._finish_file()
        self.status = "completado"
        self.progress = self.total_size or self.progress

    @staticmethod
    def _is_retryable(error) -> bool:
        if isinstance(error, DownloadError):
            return error.retryable
        response = getattr(error, "response", None)
        # 4xx (salvo 408/429) no cambia al reintentar: el enlace expiró o no hay permiso
        if response is not None and 400 <= response.status_code < 500 and response.status_code not in (408, 429):
            return False
        return True

    def _check_disk_space(self) -> bool:
        """Verifica si hay suficiente espacio en disco"""
        try:
            import shutil
            free_space = shutil.disk_usage(os.path.dirname(os.path.abspath(self.output_path))).free

            # Requerir 10% más espacio del necesario como buffer
            required_space = int(self.total_size * 1.1)

            return free_space >= required_space
        except:
            return True  # Si no se puede verificar, asumir que hay espacio

    # ------------------------------------------------------------------ tramos

    @staticmethod
    def _new_segment(start: int, end: int, downloaded: int = 0, owner: Optional[int] = None) -> Dict:
        if downloaded >= end - start + 1:
            state = "completado"
        else:
            state = "conectando" if owner is not None else "pendiente"
        return {"start": start, "end": end, "downloaded": downloaded, "inflight": 0, "owner": owner, "state": state}

    @staticmethod
    def _new_connection() -> Dict:
        return {"downloaded": 0, "state": "conectando"}

    @staticmethod
    def _remaining(segment: Dict) -> int:
        return segment["end"] - segment["start"] + 1 - segment["downloaded"]

    @staticmethod
    def _same_file(state: Dict, info: Dict) -> bool:
        """El archivo del servidor es el mismo que se empezó a descargar (tamaño y fecha o ETag)."""
        if state.get("total_size") != info.get("size"):
            return False
        if state.get("last_modified") and info.get("last_modified"):
            return state["last_modified"] == info["last_modified"]
        if state.get("etag") and info.get("etag"):
            return state["etag"] == info["etag"]
        return True

    def _restore_segments(self, state: Optional[Dict], info: Dict) -> bool:
        """Retoma los tramos de un intento o una sesión anterior si se puede continuar donde quedaron."""
        if not state or not self.resumable:
            return False
        if not self._same_file(state, info):
            print("El archivo cambió en el servidor: se descarga desde el principio")
            return False
        try:
            if os.path.getsize(self.part_path) != self.total_size:
                return False
        except OSError:
            return False  # el .part ya no está
        segments, expected_start = [], 0
        try:
            for start, end, downloaded in sorted(state["segments"]):
                start, end, downloaded = int(start), int(end), int(downloaded)
                if start != expected_start or end < start or not 0 <= downloaded <= end - start + 1:
                    return False
                segments.append(self._new_segment(start, end, downloaded))
                expected_start = end + 1
        except (KeyError, TypeError, ValueError):
            return False
        if expected_start != self.total_size:
            return False
        with self._lock:
            self.segments = segments
            self.progress = sum(segment["downloaded"] for segment in segments)
        print(f"Reanudando: {self.progress} de {self.total_size} bytes ya descargados")
        return True

    def _create_segments(self):
        """Archivo .part del tamaño final y un tramo inicial por conexión."""
        with open(self.part_path, 'wb') as f:
            _reserve_size(f, self.total_size)
        if self.total_size < 1024 * 1024:  # < 1MB: una sola parte
            count = 1
        else:
            count = max(1, min(self.threads, self.total_size // MIN_PART_SIZE))
        size = self.total_size // count
        segments = [self._new_segment(i * size, self.total_size - 1 if i == count - 1 else (i + 1) * size - 1)
                    for i in range(count)]
        with self._lock:
            self.segments = segments
            self.progress = 0

    def _claim_segment(self, index: int) -> Optional[Dict]:
        """Tramo para una conexión libre: uno sin dueño o, si no queda, la mitad del que más falta."""
        with self._lock:
            for segment in self.segments:
                if segment["owner"] is None and self._remaining(segment) > 0:
                    segment["owner"], segment["state"] = index, "conectando"
                    return segment
            busiest = max((s for s in self.segments if s["owner"] is not None), key=self._remaining, default=None)
            if busiest is None or self._remaining(busiest) < 2 * MIN_SPLIT_SIZE:
                return None
            # Segmentación dinámica: la conexión libre se queda con la segunda mitad de lo que falta
            position = busiest["start"] + busiest["downloaded"] + busiest["inflight"]
            middle = position + (busiest["end"] - position + 1) // 2
            segment = self._new_segment(middle, busiest["end"], owner=index)
            busiest["end"] = middle - 1
            self.segments.insert(self.segments.index(busiest) + 1, segment)
            return segment

    # ------------------------------------------------------------------ descarga

    def _wait_if_paused(self):
        while self.pause_flag.is_set() and not self.cancel_flag.is_set():
            time.sleep(0.1)

    def _after_chunk(self, nbytes: int):
        """Velocidad, progreso, guardado del avance y límite de velocidad tras cada bloque recibido."""
        self._update_speed(nbytes)
        if self.progress_callback:
            self._call_progress_callback()
        self._save_state()
        limit = self.speed_limit_kbps
        if limit > 0:
            # El límite se reparte entre las conexiones que están recibiendo datos
            active = max(1, sum(1 for c in self.connections if c["state"] == "descargando"))
            time.sleep(nbytes * active / (limit * 1024))

    def _single_stream_download(self):
        """Una sola conexión desde el principio: el servidor no admite rangos o no informa el tamaño."""
        segment = self._new_segment(0, max(self.total_size - 1, 0), owner=0)
        connection = self._new_connection()
        with self._lock:
            self.segments, self.connections = [segment], [connection]
            self.progress = 0
        self._speed_time, self._speed_bytes = time.time(), 0

        response = self.session.get(self.url, stream=True, timeout=30)
        with response:
            response.raise_for_status()
            segment["state"] = connection["state"] = "descargando"
            with open(self.part_path, 'wb', buffering=0) as f:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if self.cancel_flag.is_set():
                        return
                    self._wait_if_paused()
                    if chunk:
                        _write_all(f, chunk)
                        with self._lock:
                            segment["downloaded"] += len(chunk)
                            connection["downloaded"] += len(chunk)
                            self.progress += len(chunk)
                        self._after_chunk(len(chunk))
        segment["state"] = connection["state"] = "completado"

    def _multi_connection_download(self) -> bool:
        """Descarga los tramos con varias conexiones. Devuelve False si el servidor no respetó los rangos."""
        with self._lock:
            self.connections = [self._new_connection() for _ in range(self.threads)]
        self.thread_list = [threading.Thread(target=self._connection_loop, args=(i,), daemon=True)
                            for i in range(self.threads)]
        for thread in self.thread_list:
            thread.start()

        # Esperar a que terminen todos los hilos
        for thread in self.thread_list:
            thread.join()

        if self.cancel_flag.is_set():
            return True
        if self._thread_errors:
            error = self._thread_errors[0]
            if isinstance(error, RangeNotSupported):
                return False
            raise error
        with self._lock:
            pending = any(self._remaining(segment) > 0 for segment in self.segments)
        if pending:
            # Todas las conexiones se retiraron por fallos: run() reintenta desde aquí
            raise self._last_error or DownloadError("descarga incompleta")
        return True

    def _connection_loop(self, index: int):
        """Una conexión: descarga tramos hasta que no quede ninguno por tomar o por partir."""
        connection = self.connections[index]
        failures = 0
        while not (self.cancel_flag.is_set() or self._abort_flag.is_set()):
            self._wait_if_paused()
            segment = None if self.cancel_flag.is_set() else self._claim_segment(index)
            if segment is None:
                break
            before = segment["downloaded"]
            try:
                self._download_segment(segment, connection)
                failures = 0
            except Exception as e:
                with self._lock:
                    segment["owner"], segment["inflight"] = None, 0  # lo retoma otra conexión (o esta)
                    if self._remaining(segment) > 0:
                        segment["state"] = "error"
                    progressed = segment["downloaded"] > before
                if isinstance(e, RangeNotSupported) or not self._is_retryable(e):
                    print(f"Error en la conexión {index + 1}: {e}")
                    with self._lock:
                        self._thread_errors.append(e)
                    self._abort_flag.set()
                    connection["state"] = "error"
                    return
                self._last_error = e
                failures = 1 if progressed else failures + 1
                print(f"Conexión {index + 1}: {e} (fallo {failures}/{MAX_CONNECTION_FAILURES})")
                if failures >= MAX_CONNECTION_FAILURES:
                    connection["state"] = "error"
                    return  # esta conexión se retira; siguen las demás
                connection["state"] = "reintentando"
                if self.cancel_flag.wait(min(2 * failures, 10)):
                    return
        if connection["state"] != "error":
            connection["state"] = "completado"

    @staticmethod
    def _range_starts_at(response, position: int) -> bool:
        match = re.match(r"bytes\s+(\d+)-", response.headers.get("content-range", ""))
        return match is None or int(match.group(1)) == position

    def _download_segment(self, segment: Dict, connection: Dict):
        """Descarga lo que falta del tramo; para antes si otra conexión se quedó con su final."""
        with self._lock:
            position = segment["start"] + segment["downloaded"]
            end = segment["end"]
        if position > end:
            segment["state"] = "completado"
            return
        connection["state"] = "conectando"
        response = self.session.get(self.url, headers={'Range': f'bytes={position}-{end}'}, stream=True, timeout=30)
        with response:
            response.raise_for_status()
            if response.status_code != 206 or not self._range_starts_at(response, position):
                # Con 200 llega el archivo completo: escribirlo en este tramo lo corrompería
                raise RangeNotSupported(f"el servidor respondió {response.status_code} a una petición por rangos")
            segment["state"] = connection["state"] = "descargando"

            # Sin búfer: lo contado como descargado ya está en el disco (para reanudar sin huecos)
            with open(self.part_path, "r+b", buffering=0) as f:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if self.cancel_flag.is_set() or self._abort_flag.is_set():
                        return
                    self._wait_if_paused()
                    if not chunk:
                        continue
                    with self._lock:
                        position = segment["start"] + segment["downloaded"]
                        data = chunk[:max(0, segment["end"] - position + 1)]  # su final pudo pasar a otra conexión
                        segment["inflight"] = len(data)
                    if data:
                        f.seek(position)
                        _write_all(f, data)
                    with self._lock:
                        segment["inflight"] = 0
                        segment["downloaded"] += len(data)
                        connection["downloaded"] += len(data)
                        self.progress += len(data)
                        finished = self._remaining(segment) <= 0
                    if data:
                        self._after_chunk(len(data))
                    if finished:
                        break

        with self._lock:
            finished = self._remaining(segment) <= 0
            if finished:
                segment["state"] = "completado"
        if not finished and not (self.cancel_flag.is_set() or self._abort_flag.is_set()):
            raise DownloadError("la conexión se cortó antes de terminar su parte")

    def _finish_file(self):
        """Renombra el .part al nombre final."""
        for attempt in range(5):
            try:
                os.replace(self.part_path, self.output_path)
                return
            except PermissionError:
                # El antivirus puede estar revisando el archivo recién escrito
                time.sleep(0.2 * (attempt + 1))
        os.replace(self.part_path, self.output_path)

    # ------------------------------------------------------------------ avance

    def snapshot(self) -> Optional[Dict]:
        """Avance para reanudar más tarde, o None si esta descarga no se puede reanudar."""
        with self._lock:
            if not (self.resumable and self.total_size and self.segments):
                return None
            return {
                "total_size": self.total_size,
                "etag": self._etag,
                "last_modified": self._last_modified,
                "segments": [[s["start"], s["end"], s["downloaded"]] for s in self.segments],
            }

    def get_segments(self):
        """Copia de los tramos y las conexiones para la interfaz (cambian desde otros hilos)."""
        with self._lock:
            return [dict(s) for s in self.segments], [dict(c) for c in self.connections]

    def _save_state(self, force: bool = False):
        """Entrega el avance a state_callback, como mucho cada STATE_SAVE_INTERVAL segundos."""
        if not self.state_callback:
            return
        now = time.time()
        with self._lock:
            if not force and now - self._last_state_save < STATE_SAVE_INTERVAL:
                return
            self._last_state_save = now
        state = self.snapshot()
        if state:
            try:
                self.state_callback(state)
            except Exception as e:
                print(f"No se pudo guardar el avance: {e}")

    def _update_speed(self, bytes_downloaded: int):
        """Actualiza la velocidad actual (no la media desde el inicio) y el tiempo restante"""
        current_time = time.time()
        with self._lock:
            if self._speed_time is None:
                self._speed_time, self._speed_bytes = current_time, self.progress
                return
            elapsed = current_time - self._speed_time
            if elapsed < 0.5:
                return
            instant = (self.progress - self._speed_bytes) / elapsed
            # Suavizado para que la cifra no salte en cada muestra
            self.download_speed = instant if not self.download_speed else 0.7 * self.download_speed + 0.3 * instant
            self._speed_time, self._speed_bytes = current_time, self.progress

            # Calcular ETA
            if self.download_speed > 0 and self.total_size > 0:
                remaining_bytes = self.total_size - self.progress
                self.eta = remaining_bytes / self.download_speed

    def _call_progress_callback(self):
        """Llama al callback de progreso si existe"""
        if self.progress_callback:
            progress_info = {
                'progress': self.progress,
                'total_size': self.total_size,
                'percentage': (self.progress / self.total_size * 100) if self.total_size > 0 else 0,
                'speed': self.download_speed,
                'eta': self.eta,
                'status': self.status
            }
            self.progress_callback(progress_info)

    def _verify_integrity(self) -> bool:
        """Verifica la integridad del archivo descargado"""
        if not self.expected_hash:
            return True

        try:
            hash_obj = hashlib.new(self.hash_algorithm)

            with open(self.part_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_obj.update(chunk)

            calculated_hash = hash_obj.hexdigest()
            return calculated_hash.lower() == self.expected_hash.lower()

        except Exception as e:
            print(f"Error verificando integridad: {e}")
            return False

    def pause(self):
        """Pausa la descarga (y guarda el avance)"""
        self.pause_flag.set()
        self.status = "pausado"
        self._save_state(force=True)

    def resume(self):
        """Reanuda la descarga"""
        self.pause_flag.clear()
        self.status = "descargando"

    def cancel(self):
        """Cancela la descarga (el .part y el avance quedan para poder reanudarla)"""
        self.cancel_flag.set()
        self.status = "cancelado"
        self._save_state(force=True)

    def get_progress_info(self) -> Dict:
        """Obtiene información detallada del progreso"""
        return {
            'progress': self.progress,
            'total_size': self.total_size,
            'percentage': (self.progress / self.total_size * 100) if self.total_size > 0 else 0,
            'speed': self.download_speed,
            'eta': self.eta,
            'status': self.status,
            'threads': len(self.thread_list),
            'retry_count': self.retry_count,
            'url': self.url,
            'output_path': self.output_path
        }


# Función de conveniencia
def download_file(url: str, output_path: str, **kwargs) -> EnhancedDownloadTask:
    """Función de conveniencia para crear y ejecutar una descarga"""
    task = EnhancedDownloadTask(url, output_path, **kwargs)
    return task


if __name__ == "__main__":
    # Test del downloader mejorado
    def progress_callback(info):
        print(f"\rProgreso: {info['percentage']:.1f}% - "
              f"Velocidad: {info['speed']/1024:.1f} KB/s - "
              f"ETA: {info['eta']:.0f}s", end="")

    # Test con archivo de ejemplo
    test_url = "https://www.python.org/ftp/python/3.9.7/python-3.9.7-amd64.exe"
    test_path = "test_download.exe"

    downloader = EnhancedDownloadTask(
        url=test_url,
        output_path=test_path,
        threads=4,
        progress_callback=progress_callback
    )

    print(f"Descargando: {test_url}")
    downloader.run()
    print(f"\nEstado final: {downloader.status}")
