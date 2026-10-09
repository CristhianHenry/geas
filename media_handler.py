import functools
import glob
import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Callable, Tuple
from urllib.parse import urljoin, urlparse

import requests
import yt_dlp
from yt_dlp.extractor import gen_extractor_classes
from yt_dlp.networking.impersonate import ImpersonateTarget

import network
import paths
from browser_context import BrowserContext, is_http_url

YOUTUBE_DOMAINS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
MAX_STREAM_CANDIDATES = 4

VIDEO_URL_PATTERN = re.compile(r'https?://[^\s"\'<>\\]+\.(?:mp4|m3u8|webm|mpd)(?:\?[^\s"\'<>\\]*)?', re.IGNORECASE)
HTTP_ERROR_PATTERN = re.compile(r"HTTP Error \d{3}: [^.\n]*")
# Errores con los que vale la pena reintentar con otras cabeceras
ACCESS_DENIED_MARKERS = ("HTTP Error 401", "HTTP Error 403", "HTTP Error 404", "downloaded file is empty")
# Cómo pide los fragmentos un reproductor. yt-dlp por defecto se presenta como una
# navegación ("Accept: text/html...", "Sec-Fetch-Mode: navigate") y muchos servidores
# de video rechazan eso para los fragmentos.
MEDIA_REQUEST_HEADERS = {"Accept": "*/*", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "video"}
# Cabeceras cuyo valor se puede anotar en el log (las demás pueden llevar tokens)
LOGGABLE_HEADERS = {"Referer", "Origin", "Accept", "Sec-Fetch-Mode", "Sec-Fetch-Dest", "Sec-Fetch-Site"}

logger = logging.getLogger(__name__)


class _YdlLogger:
    """
    Envía los avisos y errores de yt-dlp durante la descarga a geas.log y
    recuerda el último error HTTP (los reintentos de fragmentos llegan como
    mensajes de pantalla, no como avisos).
    """

    def __init__(self):
        self.http_error = ""
        self.needs_ffmpeg = False  # yt-dlp no pudo reempaquetar el video (sin ffmpeg)

    def _remember(self, msg):
        if "Install ffmpeg" in msg or "ffmpeg not found" in msg:
            self.needs_ffmpeg = True
        match = HTTP_ERROR_PATTERN.search(msg)
        if match:
            self.http_error = match.group(0).strip()

    def debug(self, msg):
        # El resto (progreso, pasos) es demasiado detalle para el log
        if "Got error" in msg or "Skipping fragment" in msg:
            self.warning(msg)

    def info(self, msg):
        pass

    def warning(self, msg):
        self._remember(msg)
        logger.warning(f"yt-dlp: {msg}")

    def error(self, msg):
        self._remember(msg)
        logger.error(f"yt-dlp: {msg}")


@dataclass
class Candidate:
    """Una URL que se intentará analizar con yt-dlp y las cabeceras con las que pedirla."""
    url: str
    headers: Dict[str, str]
    is_stream: bool = False
    download_headers: Optional[Dict[str, str]] = None  # las de los fragmentos, si se capturaron


def _host_matches(url: str, domains) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def _short(url: str, size: int = 80) -> str:
    return url if len(url) <= size else url[:size - 3] + "..."


def _registry_path_dirs() -> List[str]:
    """PATH de usuario y de sistema tal como está ahora en el registro de Windows."""
    import winreg
    dirs = []
    keys = [(winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")]
    for root, subkey in keys:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        dirs += [os.path.expandvars(part) for part in value.split(";") if part]
    return dirs


def find_ffmpeg() -> Optional[str]:
    """
    Carpeta donde está ffmpeg, o None. Además del PATH del proceso (cuando el
    navegador abre Geas, hereda su PATH, que puede ser anterior a instalar
    ffmpeg) mira el PATH actual del registro y las carpetas habituales.
    """
    found = shutil.which("ffmpeg")
    if found:
        return os.path.dirname(found)
    executable = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = [os.path.join(paths.APP_DIR, "ffmpeg", "bin")]
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates += _registry_path_dirs()
        candidates += [os.path.join(local, "Microsoft", "WinGet", "Links")]
        candidates += glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "*", "bin"))
        candidates += [r"C:\ffmpeg\bin", os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "ffmpeg", "bin"),
                       r"C:\ProgramData\chocolatey\bin", os.path.join(os.path.expanduser("~"), "scoop", "shims")]
    for folder in candidates:
        if folder and os.path.isfile(os.path.join(folder, executable)):
            return folder
    return None


def _apply_proxy(ydl_opts):
    """El proxy elegido en Opciones (sin él, yt-dlp usa el del sistema)."""
    proxy = network.ytdlp_proxy()
    if proxy is not None:
        ydl_opts['proxy'] = proxy


@functools.lru_cache(maxsize=1)
def impersonation_available() -> bool:
    """True si yt-dlp puede imitar la conexión (huella TLS) de Chrome: requiere el paquete curl_cffi."""
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            return bool(ydl._impersonate_target_available(ImpersonateTarget('chrome')))
    except Exception:
        return False


def _for_impersonation(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Al imitar a Chrome, el User-Agent y los sec-ch-ua los pone curl_cffi (deben coincidir con su huella)."""
    return {k: v for k, v in (headers or {}).items() if k != "User-Agent" and not k.lower().startswith("sec-ch-")}


@functools.lru_cache(maxsize=256)
def has_specific_extractor(url: str) -> bool:
    """True si yt-dlp tiene un extractor propio para la URL (YouTube, Vimeo, ...), no el genérico."""
    for ie in gen_extractor_classes():
        if ie.ie_key() == "Generic":
            continue
        try:
            if ie.suitable(url) and ie.working():
                return True
        except Exception:
            continue
    return False


class MediaHandler:
    """
    Manejador para descargas de medios usando yt-dlp.
    Soporta extracción de metadatos y descarga de formatos específicos.
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.notice = None  # aviso de la última descarga (p. ej. falta ffmpeg)

    # ------------------------------------------------------------------ análisis

    def extract_info(self, url: str, context: Optional[BrowserContext] = None) -> Optional[Dict]:
        """
        Extrae información del video/playlist sin descargar.
        Retorna un diccionario con metadatos y formatos disponibles (ver resolve()).
        """
        info, _ = self.resolve(url, context)
        return info

    def resolve(self, url: str, context: Optional[BrowserContext] = None,
                prefer_stream: bool = False) -> Tuple[Optional[Dict], List[str]]:
        """
        Prueba las fuentes posibles del video, en este orden, hasta que yt-dlp
        obtenga formatos de alguna:
          1. el stream elegido por el usuario (si prefer_stream)
          2. páginas con extractor propio (YouTube, Vimeo, ...)
          3. streams HLS/DASH/MP4 detectados por la extensión en la pestaña
          4. páginas con el extractor genérico
          5. enlaces de video escritos en el HTML de la página

        Returns:
            (info, errores). info incluye '_geas_source' con la URL y las
            cabeceras que funcionaron, para descargar desde el mismo lugar.
        """
        ctx = context or BrowserContext()
        errors = []
        for candidate in self._candidates(url, ctx, prefer_stream):
            info = self._try_extract(candidate, ctx, errors)
            if info:
                return info, errors

        # Último intento: extraer directamente la página HTML
        for page in self._pages(url, ctx):
            info = self._extract_from_html(page, ctx, errors)
            if info:
                return info, errors
        return None, errors

    @staticmethod
    def _pages(url: str, ctx: BrowserContext, include_url: bool = True) -> List[str]:
        pages = []
        for page in ([url] if include_url else []) + [ctx.page_url, ctx.top_url]:
            if is_http_url(page) and page not in pages:
                pages.append(page)
        return pages

    @staticmethod
    def _page_headers(page: str, ctx: BrowserContext) -> Dict[str, str]:
        # Un iframe (reproductor embebido) suele exigir como Referer la página que lo contiene
        referer = ctx.top_url if ctx.top_url and page != ctx.top_url else ctx.referer
        return ctx.http_headers(extra={}, referer=referer)

    @staticmethod
    def _stream_headers(stream: Dict, ctx: BrowserContext, referer: Optional[str] = None) -> Dict[str, str]:
        # Las cabeceras capturadas por la extensión (Referer, Origin, tokens) tienen prioridad
        return ctx.http_headers(extra=stream.get("headers") or {}, referer=referer or ctx.page_url or ctx.top_url)

    @staticmethod
    def _segment_headers(stream: Dict, ctx: BrowserContext) -> Optional[Dict[str, str]]:
        """Cabeceras con las que el reproductor pidió los fragmentos (None si no se capturaron)."""
        if not stream.get("segment_headers"):
            return None
        return ctx.http_headers(extra=stream["segment_headers"], referer=ctx.page_url or ctx.top_url)

    def _candidates(self, url: str, ctx: BrowserContext, prefer_stream: bool) -> Iterator[Candidate]:
        """Genera las URLs a probar en el orden de resolve() (los streams se ordenan solo si hace falta)."""
        requested_is_stream = prefer_stream or any(s["url"] == url for s in ctx.streams)
        pages = self._pages(url, ctx, include_url=not requested_is_stream)
        specific = [p for p in pages if has_specific_extractor(p)]

        if requested_is_stream:
            requested = next((s for s in ctx.streams if s["url"] == url), {"url": url, "headers": {}})
            yield Candidate(url, self._stream_headers(requested, ctx), is_stream=True,
                            download_headers=self._segment_headers(requested, ctx))

        for page in specific:
            yield Candidate(page, self._page_headers(page, ctx))

        streams = [s for s in self._rank_streams(ctx) if s["url"] != url]
        for stream in streams[:MAX_STREAM_CANDIDATES]:
            yield Candidate(stream["url"], self._stream_headers(stream, ctx), is_stream=True,
                            download_headers=self._segment_headers(stream, ctx))

        for page in pages:
            if page not in specific:
                yield Candidate(page, self._page_headers(page, ctx))

    def _rank_streams(self, ctx: BrowserContext) -> List[Dict]:
        """
        Ordena los streams detectados: primero las listas HLS maestras (traen
        todas las calidades), luego otras HLS, DASH y archivos (los más grandes primero).
        """
        streams = list(ctx.streams)
        hls = [s for s in streams if s["kind"] == "hls"][:6]
        masters = set()
        if hls:
            jar = ctx.cookie_jar()

            def is_master(stream):
                try:
                    with requests.get(stream["url"], headers=self._stream_headers(stream, ctx),
                                      cookies=jar, timeout=6, stream=True) as r:
                        head = next(r.iter_content(65536), b"")
                    return b"#EXT-X-STREAM-INF" in head
                except requests.RequestException:
                    return False

            with ThreadPoolExecutor(max_workers=len(hls)) as pool:
                for stream, master in zip(hls, pool.map(is_master, hls)):
                    if master:
                        masters.add(stream["url"])

        kind_order = {"hls": 1, "dash": 2, "file": 3}

        def rank(item):
            index, stream = item
            if stream["url"] in masters:
                return (0, 0, index)
            size_key = -(stream["size"] or 0) if stream["kind"] == "file" else 0
            return (kind_order.get(stream["kind"], 3), size_key, index)

        return [stream for _, stream in sorted(enumerate(streams), key=rank)]

    def _try_extract(self, candidate: Candidate, ctx: BrowserContext, errors: List[str]) -> Optional[Dict]:
        """Analiza una URL con yt-dlp. Devuelve la info (con '_geas_source') o None."""
        cookie_modes = [bool(ctx.cookies)]
        if ctx.cookies and _host_matches(candidate.url, YOUTUBE_DOMAINS):
            # YouTube funciona mejor sin cookies; se usan solo si hacen falta (edad, verificación)
            cookie_modes = [False, True]

        attempts = [(use_cookies, False) for use_cookies in cookie_modes]
        while attempts:
            use_cookies, impersonate = attempts.pop(0)
            headers = _for_impersonation(candidate.headers) if impersonate else candidate.headers
            try:
                info = self._pick_entry(self._run_ydl(candidate.url, headers, ctx if use_cookies else None, impersonate))
            except Exception as e:
                message = str(e).replace("\n", " ")
                self.logger.warning(f"yt-dlp no pudo analizar {candidate.url}: {message}")
                errors.append(f"{_short(candidate.url)}: {message}")
                # Un 403 puede ser por la huella de la conexión: probar imitando a Chrome
                if "HTTP Error 403" in message and not impersonate and impersonation_available():
                    attempts.append((use_cookies, True))
                continue

            if info and (info.get("formats") or info.get("url")):
                self.logger.info(f"Video analizado desde {candidate.url} "
                                 f"({'stream' if candidate.is_stream else 'página'}, cookies: {'sí' if use_cookies else 'no'}, "
                                 f"imitando a Chrome: {'sí' if impersonate else 'no'}, cabeceras: {', '.join(headers)})")
                info["_geas_source"] = {
                    "url": candidate.url,
                    "headers": candidate.headers,
                    "download_headers": candidate.download_headers,
                    "use_cookies": use_cookies,
                    "is_stream": candidate.is_stream,
                    "impersonate": impersonate,
                }
                return info
            errors.append(f"{_short(candidate.url)}: no hay formatos descargables")
        return None

    @staticmethod
    def _run_ydl(url: str, headers: Dict[str, str], cookie_context: Optional[BrowserContext],
                 impersonate: bool = False) -> Dict:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'playlist_items': '1',  # en páginas con varios videos basta el primero
            'http_headers': headers,
            'socket_timeout': 20,
        }
        _apply_proxy(ydl_opts)
        if impersonate:
            ydl_opts['impersonate'] = ImpersonateTarget('chrome')
        with (cookie_context.cookie_file() if cookie_context else nullcontext()) as cookiefile:
            if cookiefile:
                ydl_opts['cookiefile'] = cookiefile
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

    @staticmethod
    def _pick_entry(info: Optional[Dict]) -> Optional[Dict]:
        """Si yt-dlp devolvió una lista de videos, toma el primero que tenga formatos."""
        if info and info.get("_type") == "playlist":
            for entry in info.get("entries") or []:
                if entry and (entry.get("formats") or entry.get("url")):
                    return entry
            return None
        return info

    def _extract_from_html(self, url: str, ctx: BrowserContext, errors: List[str]) -> Optional[Dict]:
        """
        Intento de extraer video directamente del HTML de la página.
        Esto es un fallback cuando yt-dlp no puede manejar el sitio.
        """
        try:
            from bs4 import BeautifulSoup

            response = requests.get(url, headers=self._page_headers(url, ctx),
                                    cookies=ctx.cookie_jar(), timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Buscar elementos <video> y <source>
            found = []
            for video in soup.find_all('video'):
                for src in [video.get('src')] + [source.get('src') for source in video.find_all('source')]:
                    if src:
                        found.append(urljoin(response.url, src))

            # Buscar en el HTML (y en JSON con barras escapadas) URLs de video
            found.extend(VIDEO_URL_PATTERN.findall(response.text.replace('\\/', '/')))

            video_urls = []
            for video_url in found:
                if is_http_url(video_url) and video_url not in video_urls:
                    video_urls.append(video_url)
            if not video_urls:
                self.logger.error("No se encontraron URLs de video en el HTML")
                return None

            self.logger.info(f"Extracción HTML: encontradas {len(video_urls)} URLs")
            for video_url in video_urls[:3]:
                headers = ctx.http_headers(extra={}, referer=response.url)
                info = self._try_extract(Candidate(video_url, headers, is_stream=True), ctx, errors)
                if info:
                    return info
            return None

        except Exception as e:
            self.logger.error(f"Error en extracción HTML: {e}")
            errors.append(f"{_short(url)}: {e}")
            return None

    # ------------------------------------------------------------------ formatos

    def get_formats(self, info: Dict) -> List[Dict]:
        """
        Retorna una lista simplificada y agrupada de formatos (Smart View).
        Agrupa por resolución y asegura que incluyan audio (video+audio).
        """
        formats_raw = info.get('formats') or []

        # 1. Encontrar el mejor audio (para estimar tamaños)
        audio_formats = [f for f in formats_raw if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
        best_audio = max(audio_formats, key=lambda x: x.get('tbr', 0) or 0) if audio_formats else None
        best_audio_size = (best_audio.get('filesize') or best_audio.get('filesize_approx') or 0) if best_audio else 0

        # 2. Agrupar videos por resolución (altura)
        resolutions = {}

        for f in formats_raw:
            # Ignorar audio-only aquí
            if f.get('vcodec') in ['none', None]:
                continue

            height = f.get('height')
            if not height:
                continue

            # Clave única: resolución
            if height not in resolutions:
                resolutions[height] = []
            resolutions[height].append(f)

        smart_formats = []

        # 3. Construir opciones para cada resolución
        for height, subformats in resolutions.items():
            # Elegir el mejor video de esta resolución
            # Prioridad: H.264 (lo abre cualquier reproductor, sin convertir) > mp4 > mayor bitrate
            best_video = sorted(subformats, key=lambda x: (
                1 if str(x.get('vcodec') or '').startswith(('avc1', 'h264')) else 0,
                1 if x.get('ext') == 'mp4' else 0,
                x.get('tbr', 0) or 0
            ), reverse=True)[0]

            vid_id = best_video['format_id']
            # Construir ID de descarga combinado (video + bestaudio)
            # Nota: si el video ya tiene audio (vcodec!=none y acodec!=none), usarlo directo es seguro,
            # pero yt-dlp suele separar streams en alta calidad.
            has_audio = best_video.get('acodec') != 'none'

            if has_audio:
                final_id = vid_id
                final_note = "Direct"
                estimated_size = best_video.get('filesize') or best_video.get('filesize_approx')
            else:
                # "/vid": si el sitio no ofrece audio aparte, descargar el video solo
                final_id = f"{vid_id}+bestaudio/{vid_id}"
                final_note = "Video+Audio"
                vid_size = best_video.get('filesize') or best_video.get('filesize_approx') or 0
                estimated_size = vid_size + best_audio_size if vid_size and best_audio_size else None

            entry = {
                'format_id': final_id,
                'ext': 'mp4', # Forzaremos contenedor mp4 al final
                'resolution': f"{height}p",
                'filesize': estimated_size,
                'filesize_approx': None, # Ya unificado en filesize
                'vcodec': best_video.get('vcodec'),
                'acodec': best_video.get('acodec') if has_audio else (best_audio.get('acodec') if best_audio else 'unknown'),
                'note': final_note,
                'tbr': (best_video.get('tbr') or 0) + (best_audio.get('tbr') or 0 if not has_audio and best_audio else 0),
                'type': 'video'
            }
            smart_formats.append(entry)

        # 4. Ordenar por resolución descendente
        smart_formats.sort(key=lambda x: int(x['resolution'].replace('p', '')), reverse=True)

        # Videos sin resolución conocida (MP4 directos, muchos sitios genéricos)
        if not smart_formats and any(f.get('vcodec') != 'none' for f in formats_raw):
            smart_formats.append({
                'format_id': 'bv*+ba/b',
                'ext': 'mp4',
                'resolution': 'Mejor calidad',
                'filesize': info.get('filesize') or info.get('filesize_approx'),
                'filesize_approx': None,
                'vcodec': 'auto',
                'acodec': 'auto',
                'note': 'Auto',
                'tbr': 0,
                'type': 'video'
            })

        # 5. Agregar opción "Solo Audio" al final
        if best_audio:
            smart_formats.append({
                'format_id': 'bestaudio/best',
                'ext': 'mp3',
                'resolution': 'Solo audio (MP3)',
                'filesize': best_audio_size,
                'filesize_approx': None,
                'vcodec': 'none',
                'acodec': best_audio.get('acodec'),
                'note': 'Mejor calidad',
                'tbr': best_audio.get('tbr', 0),
                'type': 'audio'
            })

        return smart_formats

    def get_raw_formats(self, info: Dict) -> List[Dict]:
        """
        Retorna la lista cruda original (para modo debug/avanzado).
        (Lógica anterior de get_formats)
        """
        formats = []
        if 'formats' not in info:
            return formats

        for f in info['formats']:
            if f.get('vcodec') == 'none' and f.get('acodec') == 'none':
                continue

            format_data = {
                'format_id': f.get('format_id'),
                'ext': f.get('ext'),
                'resolution': f.get('resolution', 'N/A'),
                'filesize': f.get('filesize'),
                'filesize_approx': f.get('filesize_approx'),
                'vcodec': f.get('vcodec'),
                'acodec': f.get('acodec'),
                'note': f.get('format_note', ''),
                'tbr': f.get('tbr', 0),
                'type': 'video' if f.get('vcodec') != 'none' else 'audio'
            }
            if format_data['resolution'] == 'audio only':
                format_data['resolution'] = 'Audio'

            formats.append(format_data)

        formats.sort(key=lambda x: x.get('tbr', 0) or 0, reverse=True)
        return formats

    # ------------------------------------------------------------------ descarga

    def download_stream(self, url: str, format_id: str, output_path: str,
                       progress_callback: Callable = None,
                       status_callback: Callable = None,
                       check_cancelled_cb: Callable = None,
                       context: Optional[BrowserContext] = None,
                       source: Optional[Dict] = None,
                       progress_info_callback: Callable = None):
        """
        Descarga un formato específico.

        source: '_geas_source' del análisis (URL, cabeceras y uso de cookies)
                para descargar desde el mismo lugar del que salieron los formatos.
        progress_info_callback: recibe el diccionario de progreso de yt-dlp
                (bytes descargados, total, velocidad, tiempo restante).
        """
        source = source or {}
        url = source.get('url') or url
        headers = source.get('headers') or (context.http_headers() if context else None)
        cookie_context = context if context and source.get('use_cookies', True) else None

        # Configurar hooks para progreso
        def progress_hook(d):
            # Verificar cancelación
            if check_cancelled_cb and check_cancelled_cb():
                raise Exception("DownloadCancelled")
            if progress_info_callback:
                progress_info_callback(d)

            if d['status'] == 'downloading':
                if progress_callback:
                    # Calcular porcentaje
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        percent = (downloaded / total) * 100
                        progress_callback(percent)

                    # Velocidad y ETA
                    speed = d.get('speed', 0)
                    eta = d.get('eta', 0)
                    if status_callback:
                        speed_str = f"{speed/1024/1024:.1f} MB/s" if speed else "..."
                        eta_str = f"{eta}s" if eta else "..."
                        status_callback(f"Descargando: {speed_str} - ETA: {eta_str}")

            elif d['status'] == 'finished':
                if progress_callback:
                    progress_callback(100)
                if status_callback:
                    status_callback("Procesando/Convirtiendo...")

        # Opciones de descarga
        ydl_opts = {
            'format': format_id,
            'outtmpl': output_path,  # yt-dlp añadirá la extensión si falta
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': False,
            'noplaylist': True,
            # Si un fragmento no se puede descargar, fallar con el motivo en vez de
            # omitirlo en silencio (video con huecos o "The downloaded file is empty")
            'skip_unavailable_fragments': False,
            # Como en la línea de comandos de yt-dlp (usado como librería no reintenta nada)
            'retries': 10,
            'fragment_retries': 10,
            # Opciones para asegurar mejor compatibilidad
            'merge_output_format': 'mp4',  # Preferir MP4 al mezclar
        }
        _apply_proxy(ydl_opts)
        # Con ffmpeg, yt-dlp reempaqueta los HLS en un MP4 normal (con índice: se puede adelantar)
        ffmpeg_dir = find_ffmpeg()
        if ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = ffmpeg_dir
        self.notice = None

        # Si es solo audio, convertir a mp3 (opcional, pero común en IDM)
        if format_id == 'bestaudio/best':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        is_stream = source.get('is_stream', False)
        download_headers = source.get('download_headers')
        segment_url = self._first_segment_url(url, headers, cookie_context) if is_stream else None
        if segment_url:
            segment_host = urlparse(segment_url).netloc.lower()
            self.logger.info(f"Primer fragmento en {segment_host}")
            # Fragmentos que la extensión no reconoció (disfrazados de imagen, etc.):
            # se usan las últimas cabeceras que el navegador envió a ese servidor
            captured = context.host_headers.get(segment_host) if context else None
            if not download_headers and captured:
                download_headers = context.http_headers(extra=captured, referer=context.page_url or context.top_url)

        variants = self._download_variants(url, headers, download_headers, is_stream, source.get('impersonate', False))
        for attempt, (attempt_headers, impersonate) in enumerate(variants, 1):
            # Avisos y errores (reintentos de fragmentos, HTTP 403...) van a geas.log
            ydl_logger = _YdlLogger()
            ydl_opts['logger'] = ydl_logger
            if attempt_headers:
                ydl_opts['http_headers'] = attempt_headers
            if impersonate:
                ydl_opts['impersonate'] = ImpersonateTarget('chrome')
            else:
                ydl_opts.pop('impersonate', None)
            self.logger.info(f"Descarga intento {attempt}/{len(variants)}{' imitando a Chrome' if impersonate else ''}: "
                             f"{self._describe_headers(attempt_headers or {})}")
            try:
                with (cookie_context.cookie_file() if cookie_context else nullcontext()) as cookiefile:
                    if cookiefile:
                        ydl_opts['cookiefile'] = cookiefile
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                if ydl_logger.needs_ffmpeg:
                    self.notice = "sin ffmpeg: puede trabarse al adelantar"
                return True

            except Exception as e:
                error_msg = str(e)
                if error_msg == "DownloadCancelled":
                    raise

                denied = any(marker in f"{error_msg} {ydl_logger.http_error}" for marker in ACCESS_DENIED_MARKERS)
                if denied and attempt < len(variants):
                    # El servidor rechazó la descarga: probar con otras cabeceras
                    self.logger.warning(f"Acceso denegado ({ydl_logger.http_error or error_msg}); "
                                        f"se prueba con otras cabeceras")
                    continue

                # Verificar si es un error de URL no soportada
                if "Unsupported URL" in error_msg or isinstance(e, yt_dlp.utils.UnsupportedError):
                    # Sitio no soportado - intentar descarga directa
                    self.logger.warning(f"Sitio no soportado para descarga, intentando descarga directa: {url}")
                    try:
                        return self._direct_download(url, output_path, attempt_headers, cookie_context,
                                                     progress_callback, check_cancelled_cb)
                    except Exception as e2:
                        if str(e2) != "DownloadCancelled":
                            self.logger.error(f"Error en descarga directa {url}: {e2}")
                            if status_callback:
                                status_callback(f"Error: {str(e2)}")
                        raise e2

                # Otro tipo de error: con el motivo real si el servidor rechazó los fragmentos
                if denied:
                    if segment_url:
                        # Con las mejores cabeceras sin imitación (requests no imita a Chrome)
                        diagnosis_headers = download_headers or {**(headers or {}), **MEDIA_REQUEST_HEADERS}
                        self._log_segment_diagnosis(segment_url, diagnosis_headers, cookie_context)
                    if ydl_logger.http_error:
                        hint = "" if impersonation_available() else (
                            "; puede que el servidor solo acepte la conexión de un navegador: "
                            "instala curl_cffi para que Geas la imite")
                        e = Exception(f"El servidor rechazó la descarga ({ydl_logger.http_error}){hint}")
                self.logger.error(f"Error descargando {url}: {e}")
                if status_callback:
                    status_callback(f"Error: {str(e)}")
                raise e

    @staticmethod
    def _download_variants(url: str, headers: Optional[Dict], download_headers: Optional[Dict] = None,
                           is_stream: bool = False, prefer_impersonation: bool = False) -> List[Tuple[Optional[Dict], bool]]:
        """
        (cabeceras, imitar a Chrome) a probar, en orden, si el servidor rechaza la descarga:
          1. las que usó el reproductor para pedir los fragmentos (si se capturaron)
          2. las del navegador; en un stream, como las pide un reproductor y no como
             una navegación
          3. lo mismo imitando la conexión de Chrome, si curl_cffi está instalado
             (algunos servidores, como Cloudflare, rechazan la huella TLS de Python)
          4. con Referer del propio servidor del video (así lo envía el reproductor HLS
             de Chrome cuando un iframe abre la lista .m3u8) y 5. sin Referer
        """
        if not headers and not download_headers:
            return [(headers, prefer_impersonation)]
        headers = headers or {}
        if is_stream:
            headers = {**headers, **MEDIA_REQUEST_HEADERS}
        parsed = urlparse(url)
        base = {k: v for k, v in headers.items() if k not in ("Referer", "Origin")}
        own_referer = {**base, "Referer": f"{parsed.scheme}://{parsed.netloc}/"}

        plain = [(download_headers, False), (headers, False)]
        impersonated = []
        if impersonation_available():
            impersonated = [(_for_impersonation(download_headers), True), (_for_impersonation(headers), True)]
            fallbacks = [(_for_impersonation(own_referer), True), (_for_impersonation(base), True)]
        else:
            fallbacks = [(own_referer, False), (base, False)]
        ordered = (impersonated + plain if prefer_impersonation else plain + impersonated) + fallbacks

        variants = []
        for variant in ordered:
            if variant[0] and variant not in variants:
                variants.append(variant)
        return variants

    def _first_segment_url(self, url: str, headers: Optional[Dict],
                           context: Optional[BrowserContext]) -> Optional[str]:
        """URL del primer fragmento de una lista HLS (entrando en la primera variante si es maestra)."""
        jar = context.cookie_jar() if context else None
        try:
            for _ in range(2):
                text = requests.get(url, headers=headers, cookies=jar, timeout=10).text
                if "#EXTM3U" not in text[:1024]:
                    return None
                uri = next((line.strip() for line in text.splitlines()
                            if line.strip() and not line.startswith("#")), None)
                if not uri:
                    return None
                uri = urljoin(url, uri)
                if "#EXT-X-STREAM-INF" not in text:
                    return uri
                url = uri  # lista maestra: bajar a la primera variante
        except requests.RequestException:
            return None
        return None

    def _log_segment_diagnosis(self, segment_url: str, headers: Optional[Dict],
                               context: Optional[BrowserContext]):
        """Anota qué responde el servidor de los fragmentos (Cloudflare, token caducado, etc.)."""
        host = urlparse(segment_url).netloc
        try:
            jar = context.cookie_jar() if context else None
            with requests.get(segment_url, headers=headers, cookies=jar, timeout=10, stream=True) as r:
                body = next(r.iter_content(400), b"")
                server = r.headers.get("Server", "?")
                cloudflare = "cf-ray" in r.headers or "cloudflare" in server.lower()
                details = (f"HTTP {r.status_code}, servidor: {server}, Cloudflare: {'sí' if cloudflare else 'no'}, "
                           f"cf-mitigated: {r.headers.get('cf-mitigated', '-')}, tipo: {r.headers.get('Content-Type', '?')}")
            snippet = re.sub(r"\s+", " ", body.decode("utf-8", "replace"))[:200]
            self.logger.warning(f"Diagnóstico del fragmento en {host}: {details} | respuesta: {snippet}")
        except Exception as e:
            self.logger.warning(f"Diagnóstico del fragmento en {host}: no se pudo consultar ({e})")

    @staticmethod
    def _describe_headers(headers: Dict[str, str]) -> str:
        """Cabeceras para el log: valor de las inofensivas, solo el nombre del resto."""
        return ", ".join(f"{name}={value}" if name in LOGGABLE_HEADERS else name
                         for name, value in headers.items())

    def _direct_download(self, url: str, output_path: str, headers: Optional[Dict],
                         context: Optional[BrowserContext], progress_callback: Callable = None,
                         check_cancelled_cb: Callable = None) -> bool:
        """Descarga directa (sin yt-dlp) con las cabeceras y cookies del navegador."""
        cookies = context.cookie_jar() if context else None
        with requests.get(url, headers=headers, cookies=cookies, stream=True, timeout=30) as r:
            r.raise_for_status()
            if r.headers.get('content-type', '').lower().startswith('text/html'):
                raise Exception("La URL es una página web, no un archivo de video")
            length = r.headers.get('content-length', '')
            total_size = int(length) if length.isdigit() else 0
            downloaded = 0

            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if check_cancelled_cb and check_cancelled_cb():
                        raise Exception("DownloadCancelled")
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback((downloaded / total_size) * 100)

        self.logger.info(f"✓ Descarga directa exitosa: {url}")
        return True
