from flask import Flask, request, jsonify
import logging
import time
from typing import Optional, Callable

from version import __version__

# Solo se aceptan peticiones dirigidas a esta máquina (protege contra DNS rebinding)
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
# Orígenes de extensiones; el host nativo (Python) no envía Origin
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://", "extension://")
DOWNLOAD_KINDS = {"file", "video", "stream", "auto", "links"}  # links: "Descargar todos los enlaces"

# Última vez que la extensión habló con Geas (el host nativo se identifica con X-Geas-Extension)
last_extension_contact = 0.0


def _note_extension_contact():
    global last_extension_contact
    if request.headers.get("X-Geas-Extension"):
        last_extension_contact = time.time()


class GeasServer:
    """
    Servidor API para Geas que maneja las peticiones de descarga
    desde la extensión del navegador (a través del host de Native Messaging).
    """

    def __init__(self, download_manager, request_callback: Optional[Callable] = None, port: int = 5000):
        """
        Inicializa el servidor API.

        Args:
            download_manager: Instancia del gestor de descargas
            request_callback: Función que recibe cada solicitud de descarga (dict).
                              Debe ser thread-safe (la GUI usa una señal Qt).
            port: Puerto donde correrá el servidor (default: 5000)
        """
        self.download_manager = download_manager
        self.request_callback = request_callback
        self.port = port
        self.app = Flask(__name__)

        # Configurar logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)

        # Registrar rutas
        self.app.before_request(self._reject_foreign_requests)
        self._register_routes()

    def _register_routes(self):
        """Registra las rutas del servidor"""
        self.app.route("/download", methods=["POST"])(self._download_file)
        self.app.route("/check", methods=["GET"])(self._check_server)
        self.app.route("/status", methods=["GET"])(self._get_status)

    def _reject_foreign_requests(self):
        """
        Rechaza peticiones que no vengan del host nativo o de una extensión:
        una página web cualquiera no debe poder ordenar descargas al equipo.
        """
        host = (request.host or "").rsplit(":", 1)[0].lower()
        if host not in ALLOWED_HOSTS:
            return jsonify({"error": "Host no permitido"}), 403

        origin = request.headers.get("Origin")
        if origin and not origin.startswith(EXTENSION_ORIGINS):
            return jsonify({"error": "Origen no permitido"}), 403
        return None

    def _download_file(self):
        """Endpoint para recibir descargas desde el navegador"""
        _note_extension_contact()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "No se recibieron datos"}), 400

        # Validaciones
        url = data.get("url")
        if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
            return jsonify({"error": "Falta una URL http(s) válida"}), 400

        # "is_video" es el formato de la versión anterior de la extensión
        kind = data.get("kind")
        if kind not in DOWNLOAD_KINDS:
            kind = "video" if data.get("is_video") else "auto"
        data["kind"] = kind

        if not self.request_callback:
            return jsonify({"error": "La interfaz de Geas no está lista"}), 503

        try:
            # La GUI muestra el diálogo que corresponda (calidad de video o archivo)
            self.request_callback(data)
        except Exception as e:
            logging.error(f"Error en _download_file: {e}")
            return jsonify({"error": str(e)}), 500
        return jsonify({"message": "Solicitud recibida"}), 200

    def _check_server(self):
        """Endpoint para verificar que el servidor está corriendo"""
        _note_extension_contact()
        return jsonify({"status": "running", "app": "Geas", "version": __version__}), 200

    def _get_status(self):
        """Endpoint para obtener el estado del gestor de descargas"""
        try:
            if not self.download_manager:
                return jsonify({"error": "Manager no disponible"}), 500

            tasks = self.download_manager.list_all()
            return jsonify({
                "status": "ok",
                "active_downloads": len([t for t in tasks if t.get("status") == "descargando"]),
                "total_tasks": len(tasks)
            }), 200
        except Exception as e:
            logging.error(f"Error en _get_status: {e}")
            return jsonify({"error": str(e)}), 500

    def run(self):
        """Inicia el servidor Flask"""
        try:
            self.app.run(
                host='127.0.0.1',
                port=self.port,
                debug=False,
                threaded=True,
                use_reloader=False
            )
        except Exception as e:
            logging.error(f"Error al iniciar servidor: {e}")
            raise


def start_server(manager_instance, on_request: Optional[Callable] = None, port: int = 5000):
    """
    Función de compatibilidad para iniciar el servidor API.

    Args:
        manager_instance: Instancia del gestor de descargas
        on_request: Función que recibe cada solicitud de descarga del navegador (dict)
        port: Puerto donde correrá el servidor (default: 5000)
    """
    server = GeasServer(manager_instance, on_request, port)
    server.run()
