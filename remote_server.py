# remote_server.py - Control de Geas desde el celular (página web en la red local)
"""
Al activarlo en Geas, una página web en la red local deja añadir enlaces, ver
el avance y pausar, reanudar o cancelar descargas desde el celular.

Seguridad:
  - Escucha en la red solo mientras está activado (la API de la extensión, en
    cambio, es solo local: 127.0.0.1).
  - Pide un código secreto: llega dentro del QR (?t=...) y queda en una cookie
    HttpOnly y SameSite=Strict; "Cambiar el código" deja fuera a los celulares
    que ya lo tenían.
  - Las acciones (POST) exigen además la cabecera X-Geas: otra página web abierta
    en el celular no puede enviarlas.
  - No muestra direcciones, cookies ni carpetas: solo nombres y estado.
"""
import hmac
import logging
import os
import secrets
import socket
import threading

from flask import Flask, jsonify, make_response, redirect, request, send_file
from werkzeug.serving import make_server

import paths
from enhanced_downloader import filename_from_url, sanitize_filename, url_probe
from media_handler import FORMAT_AUDIO, FORMAT_BEST, MediaHandler

COOKIE = "geas_remoto"
HTML_TYPES = ("text/html", "application/xhtml+xml")
STREAM_TYPES = ("application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl",
                "audio/x-mpegurl", "application/dash+xml")


def new_token():
    return secrets.token_urlsafe(18)


def local_ip():
    """Dirección de esta PC en la red local (con UDP no se envía nada), o None si no hay red."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.254.254.254", 1))
            ip = s.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith("127.") else ip


def analyze(url, mode):
    """
    Qué hacer con un enlace enviado desde el celular, sin preguntar nada en la PC:
    {'kind': 'file'|'video', 'url', 'name', 'format', 'source'}. Lanza ValueError con el motivo.
    mode: 'auto' (lo decide Geas), 'video' o 'audio' (MP3).
    """
    if mode == "auto":
        probe = url_probe(url)
        content_type = probe.get("content_type", "") if probe.get("ok") else ""
        if probe.get("ok") and content_type not in HTML_TYPES and content_type not in STREAM_TYPES:
            name = sanitize_filename(probe.get("filename") or filename_from_url(url, "descarga"))
            return {"kind": "file", "url": url, "name": name}
    info, errors = MediaHandler().resolve(url, None)
    if not info:
        raise ValueError("No se encontró un video descargable en esa página")
    audio = mode == "audio"
    title = sanitize_filename(info.get("title") or "", "video")
    source = info.get("_geas_source") or {}
    return {"kind": "video", "url": source.get("url") or url, "source": source,
            "name": f"{title}.{'mp3' if audio else 'mp4'}", "format": FORMAT_AUDIO if audio else FORMAT_BEST}


class RemoteServer:
    """
    Servidor de la página del celular. callbacks:
      snapshot() -> dict con las descargas (se llama desde el hilo del servidor)
      add(result) y action(id, acción) -> deben pasar el trabajo a la interfaz
    """

    def __init__(self, snapshot, add, action):
        self.snapshot, self.add, self.action = snapshot, add, action
        self.token = ""
        self._server = None
        self._thread = None
        self.app = Flask(__name__)
        self.app.logger.disabled = True
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        self.app.route("/")(self._page)
        self.app.route("/icono.png")(self._icon)
        self.app.route("/api/descargas", methods=["GET"])(self._list)
        self.app.route("/api/descargas", methods=["POST"])(self._add)
        self.app.route("/api/descargas/<entry_id>/<verb>", methods=["POST"])(self._act)

    @property
    def running(self):
        return self._server is not None

    def start(self, port, token, host="0.0.0.0"):
        """Empieza a escuchar en la red. Lanza OSError si el puerto está ocupado."""
        self.stop()
        self.token = token
        self._server = make_server(host, port, self.app, threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # --- Autorización ------------------------------------------------------------------------

    def _authorized(self, require_header=False):
        if require_header and request.headers.get("X-Geas") != "1":
            return False
        given = request.cookies.get(COOKIE, "")
        return bool(self.token) and hmac.compare_digest(given.encode(), self.token.encode())

    def _denied(self):
        return jsonify({"error": "Escanea de nuevo el código QR que muestra Geas en la PC"}), 401

    # --- Rutas ----------------------------------------------------------------------------------

    def _page(self):
        given = request.args.get("t", "")
        if given:
            if not (self.token and hmac.compare_digest(given.encode(), self.token.encode())):
                return make_response(_PAGE_DENIED, 401)
            # El código pasa a una cookie y se quita de la dirección (no queda en el historial)
            response = redirect("/", code=303)
            response.set_cookie(COOKIE, self.token, max_age=365 * 24 * 3600, httponly=True, samesite="Strict")
            return response
        if not self._authorized():
            return make_response(_PAGE_DENIED, 401)
        response = make_response(_PAGE)
        response.headers["Cache-Control"] = "no-store"
        return response

    def _icon(self):
        return send_file(paths.resource("branding", "geas-128.png"), mimetype="image/png")

    def _list(self):
        if not self._authorized():
            return self._denied()
        return jsonify(self.snapshot())

    def _add(self):
        if not self._authorized(require_header=True):
            return self._denied()
        data = request.get_json(silent=True) or {}
        url = str(data.get("url", "")).strip()
        mode = data.get("modo") if data.get("modo") in ("auto", "video", "audio") else "auto"
        if not url.lower().startswith(("http://", "https://")) or len(url) > 4000:
            return jsonify({"error": "El enlace debe empezar con http:// o https://"}), 400
        try:
            result = analyze(url, mode)
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 422
        self.add(result)
        return jsonify({"ok": True, "nombre": result["name"]})

    def _act(self, entry_id, verb):
        if not self._authorized(require_header=True):
            return self._denied()
        if verb not in ("pausar", "reanudar", "cancelar"):
            return jsonify({"error": "Acción desconocida"}), 404
        self.action(entry_id, verb)
        return jsonify({"ok": True})


_PAGE_DENIED = """<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Geas</title>
<body style="font-family:system-ui,sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem;line-height:1.5">
<h1 style="font-size:1.3rem">Geas</h1>
<p>Para usar Geas desde el celular, escanea el código QR que aparece en la PC
(Tareas → Control desde el celular).</p></body></html>"""

_PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Geas</title>
<link rel="icon" href="/icono.png">
<style>
  :root { --bg:#f3f3f3; --card:#ffffff; --text:#1b1b1b; --muted:#666; --accent:#c8102e; --line:#ddd;
          --bar:#e6e6e6; --fill:#2f7fd3; --error:#c42b1c; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#141014; --card:#221d22; --text:#ececec; --muted:#a8a8a8; --line:#3a3338;
            --bar:#3a3338; --fill:#4a90d9; --error:#ff6b5b; }
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }
  header { display:flex; align-items:center; gap:.6rem; padding:.8rem 1rem; background:var(--card);
           border-bottom:2px solid var(--accent); position:sticky; top:0; }
  header img { width:32px; height:32px; }
  header h1 { font-size:1.15rem; margin:0; }
  header small { color:var(--muted); margin-left:auto; text-align:right; }
  main { padding:1rem; max-width:40rem; margin:0 auto; }
  form { background:var(--card); padding:1rem; border-radius:12px; display:grid; gap:.6rem; }
  input, select, button { font:inherit; font-size:1rem; padding:.7rem; border-radius:8px; border:1px solid var(--line);
                          background:var(--bg); color:var(--text); width:100%; }
  button { cursor:pointer; }
  form button { background:var(--accent); color:#fff; border:none; font-weight:600; }
  #mensaje { min-height:1.4em; color:var(--muted); margin:.6rem 0 0; }
  #mensaje.error { color:var(--error); }
  h2 { font-size:1rem; margin:1.4rem 0 .6rem; }
  .item { background:var(--card); border-radius:12px; padding:.8rem 1rem; margin-bottom:.6rem; }
  .nombre { font-weight:600; overflow-wrap:anywhere; }
  .estado { color:var(--muted); font-size:.9rem; margin:.3rem 0; }
  .estado.error { color:var(--error); }
  .barra { height:8px; background:var(--bar); border-radius:4px; overflow:hidden; }
  .barra div { height:100%; background:var(--fill); }
  .acciones { display:flex; gap:.5rem; margin-top:.6rem; }
  .acciones button { width:auto; padding:.45rem .9rem; font-size:.9rem; }
  .vacio { color:var(--muted); text-align:center; padding:2rem 0; }
</style>
</head>
<body>
<header><img src="/icono.png" alt=""><h1>Geas</h1><small id="resumen"></small></header>
<main>
  <form id="formulario">
    <input id="url" type="url" inputmode="url" placeholder="Pega aquí el enlace" required autocomplete="off">
    <select id="modo">
      <option value="auto">Lo que sea (Geas decide)</option>
      <option value="video">Video (mejor calidad)</option>
      <option value="audio">Solo audio (MP3)</option>
    </select>
    <button type="submit">Descargar en la PC</button>
  </form>
  <p id="mensaje"></p>
  <h2>Descargas</h2>
  <div id="lista"><p class="vacio">Cargando…</p></div>
</main>
<script>
const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Geas": "1" } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || ("Error " + response.status));
  return data;
}

function show(text, isError = false) {
  $("mensaje").textContent = text;
  $("mensaje").className = isError ? "error" : "";
}

function render(data) {
  $("resumen").textContent = data.resumen || "";
  const list = $("lista");
  list.replaceChildren();
  if (!data.descargas.length) {
    list.innerHTML = '<p class="vacio">Todavía no hay descargas</p>';
    return;
  }
  for (const d of data.descargas) {
    const item = document.createElement("div");
    item.className = "item";
    const name = document.createElement("div");
    name.className = "nombre";
    name.textContent = d.nombre;
    const status = document.createElement("div");
    status.className = "estado" + (d.error ? " error" : "");
    status.textContent = [d.estado, d.velocidad, d.restante].filter(Boolean).join(" · ");
    item.append(name, status);
    if (d.porcentaje !== null) {
      const bar = document.createElement("div");
      bar.className = "barra";
      const fill = document.createElement("div");
      fill.style.width = Math.max(0, Math.min(100, d.porcentaje)) + "%";
      bar.append(fill);
      item.append(bar);
    }
    const actions = document.createElement("div");
    actions.className = "acciones";
    for (const [verb, label, allowed] of [["pausar", "Pausar", d.puede_pausar], ["reanudar", "Reanudar", d.puede_reanudar],
                                          ["cancelar", "Cancelar", d.puede_pausar]]) {
      if (!allowed) continue;
      const button = document.createElement("button");
      button.textContent = label;
      button.onclick = async () => {
        try { await api(`/api/descargas/${encodeURIComponent(d.id)}/${verb}`, { method: "POST" }); refresh(); }
        catch (e) { show(e.message, true); }
      };
      actions.append(button);
    }
    if (actions.children.length) item.append(actions);
    list.append(item);
  }
}

async function refresh() {
  try { render(await api("/api/descargas")); }
  catch (e) { show(e.message, true); }
}

$("formulario").onsubmit = async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  show("Analizando el enlace…");
  try {
    const result = await api("/api/descargas", { method: "POST",
      body: JSON.stringify({ url: $("url").value, modo: $("modo").value }) });
    show("Añadido a la cola: " + result.nombre);
    $("url").value = "";
    refresh();
  } catch (e) { show(e.message, true); }
  button.disabled = false;
};

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""
