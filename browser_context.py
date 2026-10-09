# browser_context.py - Contexto del navegador que acompaña a cada descarga
"""
Cuando la extensión envía una descarga adjunta lo que el navegador usaba para
acceder a ese recurso: cookies, Referer, User-Agent y cabeceras propias del
sitio. Sin esto muchos servidores responden 403 o entregan otro contenido.
"""

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

STREAM_KINDS = ("hls", "dash", "file")


def is_http_url(value) -> bool:
    return isinstance(value, str) and value.lower().startswith(("http://", "https://"))


def _canonical_header(name: str) -> str:
    return "-".join(part.capitalize() for part in name.split("-"))


def _clean_headers(raw) -> Dict[str, str]:
    """Solo cabeceras de texto y sin saltos de línea."""
    headers = {}
    if isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(name, str) and isinstance(value, str) and not any(c in value for c in "\r\n"):
                headers[_canonical_header(name.strip())] = value
    return headers


def _clean_cookie(raw) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    name, value, domain = raw.get("name"), raw.get("value"), raw.get("domain")
    if not all(isinstance(v, str) for v in (name, value, domain)) or not name or not domain:
        return None
    if any(c in name + value for c in "\t\r\n"):
        return None
    path = raw.get("path")
    expires = raw.get("expirationDate")
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path if isinstance(path, str) and path else "/",
        "secure": bool(raw.get("secure")),
        "httpOnly": bool(raw.get("httpOnly")),
        "hostOnly": bool(raw.get("hostOnly", not domain.startswith("."))),
        "expirationDate": int(expires) if isinstance(expires, (int, float)) and expires > 0 else None,
    }


def _clean_stream(raw) -> Optional[dict]:
    if not isinstance(raw, dict) or not is_http_url(raw.get("url")):
        return None
    size = raw.get("size")
    return {
        "url": raw["url"],
        "kind": raw.get("kind") if raw.get("kind") in STREAM_KINDS else "file",
        "size": int(size) if isinstance(size, (int, float)) and size > 0 else None,
        "headers": _clean_headers(raw.get("headers")),
        # Cómo pidió el reproductor el primer fragmento (puede diferir de la lista)
        "segment_url": raw["segment_url"] if is_http_url(raw.get("segment_url")) else None,
        "segment_headers": _clean_headers(raw.get("segment_headers")),
    }


def _netscape_line(cookie: dict) -> str:
    """Una cookie en el formato de cookies.txt (Netscape) que entiende yt-dlp."""
    domain = cookie["domain"]
    if cookie["hostOnly"]:
        domain = domain.lstrip(".")
    elif not domain.startswith("."):
        domain = "." + domain
    include_subdomains = "FALSE" if cookie["hostOnly"] else "TRUE"
    if cookie["httpOnly"]:
        domain = "#HttpOnly_" + domain
    return "\t".join([
        domain,
        include_subdomains,
        cookie["path"],
        "TRUE" if cookie["secure"] else "FALSE",
        str(cookie["expirationDate"] or 0),
        cookie["name"],
        cookie["value"],
    ]) + "\n"


@dataclass
class BrowserContext:
    page_url: Optional[str] = None     # página (o iframe) donde estaba el recurso
    top_url: Optional[str] = None      # URL de la pestaña
    title: Optional[str] = None        # título de la pestaña
    referer: Optional[str] = None
    user_agent: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)   # cabeceras extra para la URL principal
    cookies: List[dict] = field(default_factory=list)
    streams: List[dict] = field(default_factory=list)       # medios detectados en la pestaña
    host_headers: Dict[str, Dict[str, str]] = field(default_factory=dict)  # servidor -> últimas cabeceras usadas
    extension_version: Optional[str] = None

    @classmethod
    def from_payload(cls, data: dict) -> "BrowserContext":
        """Crea el contexto a partir del JSON enviado por la extensión (validando cada campo)."""
        def text(key):
            value = data.get(key)
            return value.strip() if isinstance(value, str) and value.strip() else None

        def url(key):
            value = data.get(key)
            return value if is_http_url(value) else None

        def items(key):
            value = data.get(key)
            return value if isinstance(value, list) else []

        host_headers = {}
        raw_hosts = data.get("host_headers")
        if isinstance(raw_hosts, dict):
            for host, headers in list(raw_hosts.items())[:30]:
                cleaned = _clean_headers(headers)
                if isinstance(host, str) and host and cleaned:
                    host_headers[host.lower()] = cleaned

        return cls(
            page_url=url("page_url"),
            top_url=url("top_url"),
            title=text("title"),
            referer=url("referer"),
            user_agent=text("user_agent"),
            headers=_clean_headers(data.get("headers")),
            cookies=[c for c in map(_clean_cookie, items("cookies")) if c],
            streams=[s for s in map(_clean_stream, items("streams")) if s],
            host_headers=host_headers,
            extension_version=text("extension_version"),
        )

    def summary(self) -> str:
        """Resumen para el log: servidores y nombres de cabeceras, sin valores de cookies ni tokens."""
        def host(url):
            return urlparse(url).netloc if url else "-"

        def names(headers):
            return ", ".join(headers) or "sin cabeceras"

        streams = "; ".join(
            f"{s['kind']} {host(s['url'])} [{names(s['headers'])}]"
            + (f" fragmentos {host(s['segment_url'])} [{names(s['segment_headers'])}]" if s.get("segment_url") else "")
            for s in self.streams[:5]) or "ninguno"
        return (f"extensión {self.extension_version or 'anterior a 1.2.1'} | página {host(self.page_url)} | "
                f"streams: {streams} | servidores con cabeceras: {', '.join(self.host_headers) or 'ninguno'} | "
                f"cookies: {len(self.cookies)}")

    def http_headers(self, extra: Optional[Dict[str, str]] = None, referer: Optional[str] = None) -> Dict[str, str]:
        """
        Cabeceras para repetir la petición como la hizo el navegador.

        Args:
            extra: Cabeceras capturadas para esa URL (por defecto, las de la URL principal)
            referer: Referer a usar si las cabeceras capturadas no traen uno
        """
        headers = {"User-Agent": self.user_agent or DEFAULT_USER_AGENT}
        if referer or self.referer:
            headers["Referer"] = referer or self.referer
        headers.update(self.headers if extra is None else extra)
        return headers

    def cookie_jar(self) -> requests.cookies.RequestsCookieJar:
        """Cookies para requests, cada una limitada a su dominio."""
        jar = requests.cookies.RequestsCookieJar()
        for cookie in self.cookies:
            domain = cookie["domain"].lstrip(".") if cookie["hostOnly"] else cookie["domain"]
            jar.set(cookie["name"], cookie["value"], domain=domain,
                    path=cookie["path"], secure=cookie["secure"])
        return jar

    @contextmanager
    def cookie_file(self):
        """
        Archivo temporal cookies.txt para yt-dlp. Se borra al salir del bloque.
        Devuelve None si no hay cookies.
        """
        if not self.cookies:
            yield None
            return
        fd, path = tempfile.mkstemp(prefix="geas_cookies_", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for cookie in self.cookies:
                    f.write(_netscape_line(cookie))
            yield path
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
