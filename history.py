#histoy.py
# Registro persistente de descargas: es la lista principal de Geas (como en IDM,
# las descargas terminadas siguen en la lista hasta que se eliminan).
import json
import os
import threading
import time
import uuid
from datetime import datetime

import paths

HISTORY_FILE = paths.data("download_history.json")


def _now():
    return datetime.now().isoformat(timespec='seconds')


class DownloadHistory:
    def __init__(self):
        self.history = []
        self._lock = threading.Lock()  # las tareas actualizan el registro desde sus hilos
        self._load()

    def _load(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except json.JSONDecodeError:
                self.history = []
        # Las entradas de versiones anteriores no tenían identificador
        for entry in self.history:
            entry.setdefault("id", str(uuid.uuid4()))

    def add_entry(self, url, output_path, status, size=0, entry_id=None, kind="file", **extra):
        """Agrega una descarga al registro y devuelve su id. extra: más campos (los None no se guardan)."""
        entry = {
            "id": entry_id or str(uuid.uuid4()),
            "url": url,
            "output_path": output_path,
            "status": status,
            "size": size,
            "kind": kind,  # "file" (descarga directa) o "video" (yt-dlp)
            "timestamp": _now()
        }
        entry.update({key: value for key, value in extra.items() if value is not None})
        with self._lock:
            self.history.append(entry)
            self._save()
        return entry["id"]

    def update_entry(self, entry_id, touch=True, **fields):
        """
        Actualiza una entrada (estado, tamaño, ruta, avance para reanudar...).
        Un valor None borra el campo. Con touch=False no cambia el "último
        intento" (guardados periódicos del avance). Devuelve False si no existe.
        """
        with self._lock:
            for entry in self.history:
                if entry.get("id") == entry_id:
                    for key, value in fields.items():
                        if value is None:
                            entry.pop(key, None)
                        else:
                            entry[key] = value
                    if touch:
                        entry["timestamp"] = _now()  # "último intento", como en IDM
                    self._save()
                    return True
        return False

    def get_entry(self, entry_id):
        with self._lock:
            return next((dict(e) for e in self.history if e.get("id") == entry_id), None)

    def remove_entries(self, entry_ids):
        ids = set(entry_ids)
        with self._lock:
            self.history = [e for e in self.history if e.get("id") not in ids]
            self._save()

    def _save(self):
        # Primero en un archivo aparte: si Geas se cierra a mitad de la escritura,
        # el registro anterior queda intacto (el avance se guarda cada pocos segundos)
        temp = HISTORY_FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)
        for attempt in range(5):
            try:
                os.replace(temp, HISTORY_FILE)
                return
            except PermissionError:
                # Un antivirus o el indexador de Windows pueden tenerlo abierto un instante
                time.sleep(0.05 * (attempt + 1))
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)
        try:
            os.remove(temp)
        except OSError:
            pass

    def get_history(self):
        with self._lock:
            return sorted((dict(e) for e in self.history), key=lambda x: x["timestamp"], reverse=True)

    def clear_history(self):
        with self._lock:
            self.history = []
            self._save()
