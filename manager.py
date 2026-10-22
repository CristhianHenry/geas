import dataclasses
import gc
import logging
import os
import threading
import time
import uuid

import requests

import secure_store
import video_converter
from browser_context import BrowserContext
from history import DownloadHistory
from enhanced_downloader import EnhancedDownloadTask as DownloadWorker
from media_handler import MediaHandler, remove_temp

logger = logging.getLogger(__name__)

QUEUED = "en cola"
# Estados en los que una descarga no ocupa lugar: la conversión a H.264 ya no usa la conexión
_NOT_RUNNING = ("completado", "error", "cancelado", "pausado", "convirtiendo", "en espera", QUEUED)


def _file_size(path):
    try:
        return os.path.getsize(path)
    except (OSError, TypeError):
        return 0


def _cookies_to_list(jar):
    """Cookies de requests como lista simple (para guardarlas cifradas y reanudar más tarde)."""
    return [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "secure": bool(c.secure)}
            for c in (jar or [])]


def _cookies_from_list(items):
    jar = requests.cookies.RequestsCookieJar()
    for cookie in items or []:
        try:
            jar.set(cookie["name"], cookie["value"], domain=cookie.get("domain", ""),
                    path=cookie.get("path", "/"), secure=bool(cookie.get("secure")))
        except (KeyError, TypeError, AttributeError):
            continue
    return jar


def _context_from_dict(data):
    if not isinstance(data, dict):
        return None
    names = {f.name for f in dataclasses.fields(BrowserContext)}
    try:
        return BrowserContext(**{k: v for k, v in data.items() if k in names})
    except TypeError:
        return None


class DownloadTask:
    kind = "file"

    def __init__(self, url, output_file, threads, speed_limit_kbps, manager, headers=None, cookies=None,
                 max_retries=3, task_id=None, resume_state=None):
        self.manager = manager
        self.id = task_id or str(uuid.uuid4())
        self.url = url
        self.output_file = output_file
        self.threads = threads
        self.speed_limit_kbps = speed_limit_kbps
        self.progress = 0
        self.status = "esperando"
        self.started = False

        # headers/cookies: los del navegador cuando la descarga viene de la extensión
        # resume_state: avance guardado para continuar donde quedó
        self.worker = DownloadWorker(
            self.url,
            self.output_file,
            threads=self.threads,
            speed_limit_kbps=self.speed_limit_kbps,
            headers=headers,
            cookies=cookies,
            max_retries=max_retries,
            resume_state=resume_state,
            state_callback=self._save_state
        )

        # daemon: al salir de Geas las descargas se detienen (quedan "sin terminar")
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _save_state(self, state):
        # Avance para reanudar aunque se cierre Geas (sin cambiar el "último intento")
        self.manager.history.update_entry(self.id, touch=False, resume=state, size=state["total_size"])

    def _run(self):
        self.status = "descargando"
        try:
            self.worker.run()
            self.progress = int((self.worker.progress / self.worker.total_size) * 100) if self.worker.total_size else 0
            self.status = self.worker.status
        except Exception as e:
            self.status = f"error: {e}"
        # La ruta puede cambiar si el nombre salió del servidor
        self.output_file = self.worker.output_path
        fields = {"status": self.status, "output_path": self.output_file,
                  "size": self.worker.total_size or _file_size(self.output_file)}
        if self.status == "completado":
            fields.update(resume=None, secrets=None)  # ya no hacen falta (ni las cookies guardadas)
        self.manager.history.update_entry(self.id, **fields)
        self.manager.fill_slots()  # su lugar queda libre para la siguiente de la cola

    def start(self):
        if not self.started:
            self.started = True
            self.thread.start()

    def pause(self):
        self.worker.pause()
        self.status = "pausado"

    def resume(self):
        if not self.started:  # "Descargar más tarde": todavía no había empezado
            self.start()
            return
        self.worker.resume()
        self.status = "descargando"

    def cancel(self):
        self.worker.cancel()
        self.status = "cancelado"
        if not self.started:
            self.manager.history.update_entry(self.id, status="cancelado")

    def suspend(self):
        """Al cerrar Geas: se detiene guardando el avance y queda sin terminar en el registro."""
        self.worker.pause()


class YtDownloadTask:
    """Tarea de descarga para YouTube/Media usando yt-dlp"""
    kind = "video"

    def __init__(self, url, output_path, format_id, manager, context=None, source=None, convert_h264=False,
                 task_id=None, subtitles=None):
        self.id = task_id or str(uuid.uuid4())
        self.url = url
        self.output_path = output_path
        self.format_id = format_id
        self.manager = manager
        self.context = context  # BrowserContext (cookies del navegador)
        self.source = source    # URL y cabeceras con las que se analizó el video
        self.convert_h264 = convert_h264  # convertir AV1/VP9/HEVC a H.264 al terminar
        self.subtitles = subtitles        # {'lang', 'auto', 'embed'} o None
        self.encoder = None               # quién convierte a H.264 (gráfica o procesador)
        self.handler = MediaHandler()
        self._cancelled = False
        self._paused = False
        self.started = False

        self.status = "esperando"
        self.progress = 0
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.speed_bps = 0
        self.eta_seconds = None
        self.error = None

        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True

    def start(self):
        if not self.started:
            self.started = True
            self.status = "descargando"
            self.thread.start()

    def _on_progress_info(self, d):
        if d.get('status') == 'downloading':
            self.downloaded_bytes = d.get('downloaded_bytes') or 0
            self.total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            self.speed_bps = d.get('speed') or 0
            self.eta_seconds = d.get('eta')

    def _on_convert_progress(self, percent):
        self.progress = int(percent)
        who = f" con {self.encoder}" if self.encoder else ""
        self.status = f"convirtiendo a H.264{who} ({int(percent)} %)"

    def _on_encoder(self, label):
        self.encoder = label  # "Intel Quick Sync", "el procesador"...
        self._on_convert_progress(0)

    def _convert_if_needed(self):
        """Convierte a H.264 si el video quedó en un formato que Windows no abre. Devuelve un aviso o None."""
        if not (self.convert_h264 and os.path.exists(self.output_path)
                and video_converter.needs_h264(self.output_path)):
            return self.handler.notice
        self.speed_bps, self.eta_seconds = 0, None
        self._on_convert_progress(0)
        try:
            video_converter.convert_to_h264(self.output_path, progress_callback=self._on_convert_progress,
                                            is_cancelled=lambda: self._cancelled,
                                            encoder_callback=self._on_encoder)
            return None
        except video_converter.ConversionCancelled:
            raise Exception("DownloadCancelled")
        except Exception as e:
            # La descarga sí terminó: se conserva el video original
            logger.error(f"No se pudo convertir {self.output_path} a H.264: {e}")
            return "sin convertir a H.264"

    def _add_subtitles(self):
        """Subtítulos elegidos, aparte o incrustados. Si fallan, el video ya quedó: solo se avisa."""
        if not self.subtitles or self.output_path.lower().endswith(".mp3"):
            return None
        self.speed_bps, self.eta_seconds = 0, None
        self.status = "descargando subtítulos"
        try:
            path = self.handler.download_subtitles(self.url, self.output_path, self.subtitles,
                                                   context=self.context, source=self.source)
            if self.subtitles.get("embed") and video_converter.can_embed():
                video_converter.embed_subtitles(self.output_path, path, self.subtitles["lang"])
                os.remove(path)
            return None
        except Exception as e:
            logger.error(f"No se pudieron agregar los subtítulos a {self.output_path}: {e}")
            return "sin subtítulos"

    def _run(self):
        self.error = None
        interrupted = False
        try:
            def progress_cb(percent):
                self.progress = int(percent)

            def status_cb(msg):
                if "MB/s" in msg:
                    self.status = "descargando"
                else:
                    self.status = msg

            self.status = "descargando"
            self.handler.download_stream(
                self.url, self.format_id, self.output_path,
                progress_callback=progress_cb,
                status_callback=status_cb,
                check_cancelled_cb=lambda: self._cancelled,
                context=self.context,
                source=self.source,
                progress_info_callback=self._on_progress_info
            )

            notices = [n for n in (self._convert_if_needed(), self._add_subtitles()) if n]
            # Con aviso si el video quedó sin reempaquetar (falta ffmpeg), sin convertir o sin subtítulos
            self.status = f"completado ({', '.join(notices)})" if notices else "completado"
            self.progress = 100
            self.speed_bps, self.eta_seconds = 0, None
            self.manager.history.update_entry(self.id, status="completado", size=_file_size(self.output_path),
                                              secrets=None)

        except Exception as e:
            if str(e) == "DownloadCancelled":
                interrupted = True
                if self._paused:
                    self.status = "pausado"
                else:
                    self.status = "cancelado"
                    self.manager.history.update_entry(self.id, status="cancelado")
            else:
                self.status = "error"
                self.error = str(e)
                self.manager.history.update_entry(self.id, status=f"error: {self.error}")
        if interrupted:
            # yt-dlp no cierra su .part al interrumpirlo (queda en el rastro del error) y Windows
            # no dejaría renombrarlo al reanudar en esta misma sesión: se libera ya
            gc.collect()
            if not self._paused:
                remove_temp(self.output_path)  # cancelada: sus pedacitos ya no sirven (pausada: se conservan)
        self.manager.fill_slots()  # terminó, falló o se pausó: su lugar queda libre

    def pause(self):
        self._paused = True
        self._cancelled = True

    def resume(self):
        if not self.started:  # "Descargar más tarde"
            self.start()
            return
        if self._paused:
            self._paused = False
            self._cancelled = False
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True
            self.thread.start()
            self.status = "descargando"

    def cancel(self):
        self._cancelled = True
        if not self.started:
            self.status = "cancelado"
            self.manager.history.update_entry(self.id, status="cancelado")

    def suspend(self):
        """Al cerrar Geas: detiene yt-dlp como una pausa; al reanudar sigue desde su .part."""
        self.pause()


class DownloadManager:
    def __init__(self, max_active=3):
        self.tasks = {}
        self.history = DownloadHistory()
        self.max_active = max_active  # descargas a la vez; las demás esperan su turno en la cola
        self._queue = []              # ids en espera de turno: sale primero la del principio
        self._lock = threading.RLock()
        self._closing = False         # al salir no se inicia nada más

    # ------------------------------------------------------------------
    # Cola: como mucho max_active descargas a la vez
    # ------------------------------------------------------------------

    def set_max_active(self, value):
        self.max_active = max(1, int(value))
        self.fill_slots()

    def _enqueue(self, task_id, front=False):
        with self._lock:
            if task_id in self._queue:
                self._queue.remove(task_id)
            self._queue.insert(0 if front else len(self._queue), task_id)
            self.history.update_entry(task_id, touch=False, status=QUEUED)
        self.fill_slots()

    def _dequeue(self, task_id):
        """Saca la descarga de la cola. Devuelve True si estaba en ella."""
        with self._lock:
            if task_id in self._queue:
                self._queue.remove(task_id)
                return True
            return False

    def running_count(self):
        """Descargas que están usando la conexión (ni en pausa, ni en cola, ni terminadas)."""
        return sum(1 for task_id in list(self.tasks)
                   if not (self.get_status(task_id) or {}).get("status", "").startswith(_NOT_RUNNING))

    def queued_count(self):
        return len(self._queue)

    def fill_slots(self):
        """Inicia las descargas de la cola mientras haya lugar (lo llaman también los hilos al terminar)."""
        with self._lock:
            if self._closing:
                return
            free = self.max_active - self.running_count()
            while free > 0 and self._queue:
                task = self.tasks.get(self._queue.pop(0))
                if task is None:
                    continue
                if task.started:
                    task.resume()  # estaba en pausa
                else:
                    task.start()
                self.history.update_entry(task.id, status="descargando")
                free -= 1

    # ------------------------------------------------------------------
    # Descargas
    # ------------------------------------------------------------------

    def add_download(self, url, output_file, threads=8, speed_limit_kbps=0, headers=None, cookies=None,
                     start=True, max_retries=3):
        task = DownloadTask(url, output_file, threads, speed_limit_kbps, self, headers=headers, cookies=cookies,
                            max_retries=max_retries)
        self.tasks[task.id] = task
        # Cabeceras y cookies del navegador, cifradas: para reanudar después de cerrar Geas
        secrets = {k: v for k, v in (("headers", headers), ("cookies", _cookies_to_list(cookies))) if v}
        self.history.add_entry(url, output_file, QUEUED if start else "en espera",
                               entry_id=task.id, kind=task.kind, secrets=secure_store.protect(secrets))
        if start:
            self._enqueue(task.id)
        return task.id

    def add_yt_download(self, url, output_file, format_id, context=None, source=None, convert_h264=False,
                        start=True, subtitles=None):
        task = YtDownloadTask(url, output_file, format_id, self, context=context, source=source,
                              convert_h264=convert_h264, subtitles=subtitles)
        self.tasks[task.id] = task
        secrets = {k: v for k, v in (("context", dataclasses.asdict(context) if context else None),
                                     ("source", source)) if v}
        self.history.add_entry(url, output_file, QUEUED if start else "en espera",
                               entry_id=task.id, kind=task.kind, secrets=secure_store.protect(secrets),
                               video={"format_id": format_id, "convert_h264": bool(convert_h264),
                                      "subtitles": subtitles})
        if start:
            self._enqueue(task.id)
        return task.id

    def pause_download(self, task_id):
        """Detiene la descarga; si estaba esperando en la cola, solo sale de ella."""
        task = self.tasks.get(task_id)
        if task is None:
            return
        if self._dequeue(task_id):
            if not task.started:
                self.history.update_entry(task_id, touch=False, status="en espera")
            return
        task.pause()
        self.fill_slots()

    def resume_download(self, task_id, front=True):
        """Vuelve a la cola (al principio, salvo front=False); empieza ya si hay lugar."""
        if task_id in self.tasks and (self.get_status(task_id) or {}).get("status") in ("pausado", "en espera"):
            self._enqueue(task_id, front=front)

    def cancel_download(self, task_id):
        if task_id in self.tasks:
            self._dequeue(task_id)
            self.tasks[task_id].cancel()
            self.fill_slots()

    def is_active(self, task_id):
        """True si la descarga está en curso (ni terminada, ni con error, ni cancelada)."""
        status = (self.get_status(task_id) or {}).get("status", "")
        return not status.startswith(("completado", "error", "cancelado"))

    def remove_task(self, task_id):
        """Quita la tarea de la sesión (cancelándola si sigue en curso)."""
        if task_id in self.tasks:
            self._dequeue(task_id)
            if self.is_active(task_id):
                self.tasks[task_id].cancel()
            del self.tasks[task_id]
            self.fill_slots()

    def entry_credentials(self, entry_id):
        """(cabeceras, cookies) guardadas con la descarga, o (None, None)."""
        entry = self.history.get_entry(entry_id) or {}
        secrets = secure_store.unprotect(entry.get("secrets")) or {}
        cookies = _cookies_from_list(secrets.get("cookies"))
        return secrets.get("headers") or None, cookies if len(cookies) else None

    def change_address(self, entry_id, url, headers=None, cookies=None):
        """
        Nueva dirección para una descarga a medias (su enlace venció). Lo descargado se
        conserva: como el usuario indica que es el mismo archivo, al reanudar solo se
        compara el tamaño (otro servidor puede dar otra fecha o ETag).
        headers/cookies: los del navegador si el enlace vino de él (reemplazan a los guardados).
        """
        task = self.tasks.get(entry_id)
        if task is not None:
            self._dequeue(entry_id)
            if self.is_active(entry_id):
                task.cancel()  # guarda el avance
            if task.started and task.thread.is_alive():
                task.thread.join(5)  # que suelte el .part antes de seguir con el enlace nuevo
            del self.tasks[entry_id]
        entry = self.history.get_entry(entry_id)
        if not entry:
            return False
        fields = {"url": url}
        if entry.get("resume"):
            fields["resume"] = {k: v for k, v in entry["resume"].items() if k not in ("etag", "last_modified")}
        if headers or cookies:
            secrets = {k: v for k, v in (("headers", headers), ("cookies", _cookies_to_list(cookies))) if v}
            fields["secrets"] = secure_store.protect(secrets)
        self.history.update_entry(entry_id, touch=False, **fields)
        return True

    def can_resume(self, entry_id):
        """Hay datos para continuar la descarga donde quedó (archivos: siempre; videos: si se guardó el formato)."""
        entry = self.history.get_entry(entry_id)
        if not entry or entry.get("status", "").startswith("completado"):
            return False
        return entry.get("kind") == "file" or (entry.get("kind") == "video" and bool(entry.get("video")))

    def resume_entry(self, entry_id, threads=8, speed_limit_kbps=0, max_retries=3, front=True):
        """
        Continúa una descarga que quedó a medias (al cerrar Geas, por un error o
        cancelada) desde lo ya descargado, con las cookies y cabeceras con que
        empezó. Si el archivo cambió en el servidor, empieza de nuevo.
        Pasa por la cola (al principio, salvo front=False).
        Devuelve False si no hay datos para hacerlo o si ya está en curso.
        """
        if not self.can_resume(entry_id):
            return False
        old = self.tasks.get(entry_id)
        if old is not None:
            if self.is_active(entry_id):
                return False
            if old.thread.is_alive():
                old.thread.join(5)  # la tarea anterior (recién cancelada) suelta sus archivos
        entry = self.history.get_entry(entry_id)
        secrets = secure_store.unprotect(entry.get("secrets")) or {}
        if entry["kind"] == "file":
            task = DownloadTask(entry["url"], entry["output_path"], threads, speed_limit_kbps, self,
                                headers=secrets.get("headers") or None,
                                cookies=_cookies_from_list(secrets.get("cookies")), max_retries=max_retries,
                                task_id=entry_id, resume_state=entry.get("resume"))
        else:
            video = entry["video"]
            task = YtDownloadTask(entry["url"], entry["output_path"], video.get("format_id"), self,
                                  context=_context_from_dict(secrets.get("context")), source=secrets.get("source"),
                                  convert_h264=bool(video.get("convert_h264")), task_id=entry_id,
                                  subtitles=video.get("subtitles"))
        self.tasks[entry_id] = task
        self.history.update_entry(entry_id, touch=False, auto_resume=None)
        self._enqueue(entry_id, front=front)
        return True

    def pending_auto_resume(self):
        """Descargas que se detuvieron al reiniciar Geas y deben continuar al abrirla."""
        return [e["id"] for e in self.history.get_history() if e.get("auto_resume")]

    def shutdown(self, resume_on_start=False):
        """
        Al salir de Geas: detiene las descargas en curso guardando su avance para
        reanudarlas al volver (con resume_on_start, automáticamente al abrir).
        """
        with self._lock:
            self._closing = True  # que las que se detienen no den paso a las de la cola
        stopping = []
        for task_id, task in list(self.tasks.items()):
            status = (self.get_status(task_id) or {}).get("status", "")
            if status == QUEUED:
                if resume_on_start:  # sigue en la cola al volver a abrir Geas
                    self.history.update_entry(task_id, touch=False, auto_resume=True)
            elif status in ("descargando", "obteniendo información", "esperando") or status.startswith("convirtiendo"):
                task.suspend()
                stopping.append(task)
                if resume_on_start:
                    self.history.update_entry(task_id, touch=False, auto_resume=True)
        # yt-dlp se detiene en su siguiente aviso de progreso: esperarlo deja su .part coherente
        deadline = time.time() + 5
        for task in stopping:
            if isinstance(task, YtDownloadTask) and task.thread.is_alive():
                task.thread.join(max(0.0, deadline - time.time()))

    def get_status(self, task_id):
        task = self.tasks.get(task_id)
        if not task:
            return None
        queued = task_id in self._queue

        # Handle YtDownloadTask
        if isinstance(task, YtDownloadTask):
            # Con el motivo, igual que las descargas directas ("error: ...")
            status = f"error: {task.error}" if task.status == "error" and task.error else task.status
            if queued:
                status = QUEUED
            elif not task.started and status == "esperando":
                status = "en espera"
            total = task.total_bytes
            if status.startswith("completado"):
                total = _file_size(task.output_path) or total  # tamaño final (tras convertir)
            return {
                "id": task.id,
                "kind": task.kind,
                "url": task.url,
                "output": task.output_path,
                "status": status,
                "progress": task.progress,
                "downloaded": task.downloaded_bytes,
                "total": total,
                "speed_bps": task.speed_bps,
                "eta_seconds": task.eta_seconds,
                "resumable": True,
                "segments": [],
                "connections": [],
            }

        # Handle EnhancedDownloadTask (Standard)
        worker = task.worker
        progress = 0
        if worker.total_size > 0:
            progress = int((worker.progress / worker.total_size) * 100)
        status = QUEUED if queued else (worker.status if task.started else "en espera")
        active = not status.startswith(_NOT_RUNNING)
        segments, connections = worker.get_segments()

        return {
            "id": task.id,
            "kind": task.kind,
            "url": task.url,
            "output": worker.output_path,
            "status": status,
            "progress": progress,
            "downloaded": worker.progress,
            "total": worker.total_size,
            "speed_bps": worker.download_speed if active else 0,
            "eta_seconds": worker.eta if active and worker.eta > 0 else None,
            "resumable": worker.resumable,
            "segments": segments,
            "connections": connections,
        }

    def list_all(self):
        return [self.get_status(tid) for tid in list(self.tasks)]
