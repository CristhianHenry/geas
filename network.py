# network.py - Proxy y usuarios por sitio, comunes a todas las conexiones de Geas
"""
El proxy se aplica con las variables de entorno que requests, yt-dlp y urllib
leen en cada conexión: así vale para las descargas, el análisis de videos y la
comprobación de versiones a la vez, y un cambio en Opciones rige desde la
siguiente conexión.

Certificados: todas las conexiones de Geas confían solo en los de certifi, que se
actualiza con cada versión de Geas (en octubre de 2026 quitó la raíz de eMudhra,
cuyas CA intermedias filtradas permiten falsificar cualquier web).
"""
import os
import ssl
from urllib.parse import urlparse

import certifi

PROXY_SYSTEM, PROXY_NONE, PROXY_MANUAL = "sistema", "ninguno", "manual"

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
_original_env = {key: os.environ.get(key) for key in _PROXY_VARS}  # las de Windows o del usuario
_mode = PROXY_SYSTEM
_proxy_url = ""
_logins = []  # [(sitio, usuario, contraseña)]


# Con estas variables otros programas (PostgreSQL, curl...) cambian la lista de certificados en que
# confían requests y Python, a veces por una vieja: en esta PC, una de PostgreSQL de 2024
_FOREIGN_CA_VARS = ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR")


def pin_trust_store():
    """Al abrir Geas: que requests use certifi y no una lista ajena puesta en el entorno (solo en Geas)."""
    for key in _FOREIGN_CA_VARS:
        os.environ.pop(key, None)


def ssl_context():
    """
    Para las conexiones con urllib (actualizar Geas y yt-dlp, bajar ffmpeg: código que luego se
    ejecuta). El contexto por defecto de Python en Windows toma las raíces del almacén de Windows
    pero no sus bloqueos, y así aceptaba los certificados falsos de eMudhra por la raíz de Sectigo.
    """
    return ssl.create_default_context(cafile=certifi.where())


def normalize_proxy(url):
    """'servidor:8080' -> 'http://servidor:8080'; también acepta socks5://..."""
    url = (url or "").strip()
    if url and "://" not in url:
        url = "http://" + url
    return url


def configure_proxy(mode, url=""):
    global _mode, _proxy_url
    _mode, _proxy_url = mode, normalize_proxy(url)
    for key in _PROXY_VARS:
        os.environ.pop(key, None)
        os.environ.pop(key.lower(), None)
    if mode == PROXY_NONE:
        os.environ["NO_PROXY"] = "*"  # conexión directa aunque Windows tenga un proxy configurado
    elif mode == PROXY_MANUAL and _proxy_url:
        os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = _proxy_url
        os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"  # la extensión habla con Geas sin proxy
    else:
        for key, value in _original_env.items():
            if value is not None:
                os.environ[key] = value


def ytdlp_proxy():
    """Opción 'proxy' de yt-dlp ('' = directa), o None para que use la del sistema."""
    if _mode == PROXY_NONE:
        return ""
    if _mode == PROXY_MANUAL and _proxy_url:
        return _proxy_url
    return None


def apply_settings(settings):
    """Toma el proxy y los usuarios por sitio de Opciones (guardados cifrados) y los aplica."""
    import secure_store
    configure_proxy(settings.get("proxy_mode"), secure_store.unprotect(settings.get("proxy_url")) or "")
    configure_logins([{"site": item.get("site", ""), "user": item.get("user", ""),
                       "password": secure_store.unprotect(item.get("password")) or ""}
                      for item in settings.get("site_logins") or []])


def configure_logins(logins):
    """logins: [{'site': 'ejemplo.com', 'user': ..., 'password': ...}] (contraseñas ya descifradas)."""
    global _logins
    _logins = [(item["site"].strip().lower().lstrip("."), item.get("user", ""), item.get("password", ""))
               for item in logins or [] if item.get("site", "").strip()]


def login_for(url):
    """(usuario, contraseña) para el servidor de la URL, o None. Vale también para sus subdominios."""
    host = (urlparse(url).hostname or "").lower()
    for site, user, password in _logins:
        if host == site or host.endswith("." + site):
            return user, password
    return None
