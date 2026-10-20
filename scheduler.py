import threading
import time
import uuid
from datetime import datetime
from manager import DownloadManager


class ScheduledDownload:
    def __init__(self, url, output_path, start_time, threads):
        self.id = str(uuid.uuid4())
        self.url = url
        self.output_path = output_path
        self.start_time = start_time  # datetime
        self.threads = threads
        self.status = "pendiente"


class Scheduler:
    def __init__(self, manager: DownloadManager):
        self.manager = manager
        self.tasks = []  # Lista de ScheduledDownload
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def _run(self):
        while self.running:
            now = datetime.now()
            for task in self.tasks[:]:  # Copia segura para modificación
                if task.status == "pendiente" and now >= task.start_time:
                    print(f"Iniciando descarga programada: {task.url}")
                    self.manager.add_download(task.url, task.output_path, task.threads)
                    task.status = "iniciada"
            time.sleep(1)

    def add_task(self, url, output_path, start_time, threads=8):
        task = ScheduledDownload(url, output_path, start_time, threads)
        self.tasks.append(task)
        return task.id

    def cancel_task(self, task_id):
        for task in self.tasks:
            if task.id == task_id and task.status == "pendiente":
                self.tasks.remove(task)
                return True
        return False

    def list_tasks(self):
        return [{
            "id": t.id,
            "url": t.url,
            "output_path": t.output_path,
            "start_time": t.start_time.isoformat(),
            "status": t.status
        } for t in self.tasks]
