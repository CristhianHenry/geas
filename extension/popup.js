// Geas - popup: estado de la conexión, ajustes y medios de la pestaña actual
import { DEFAULT_SETTINGS } from "./settings.js";

// Firefox usa "browser" (con promesas); Chrome y Edge, "chrome"
const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);
let currentTab = null;

async function send(message) {
  try {
    return (await api.runtime.sendMessage(message)) || { ok: false, error: "Sin respuesta" };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

function setStatus(state, title, detail = "") {
  $("statusDot").className = `status-dot ${state}`;
  $("statusTitle").textContent = title;
  $("statusDetail").textContent = detail;
}

async function refreshStatus() {
  setStatus("", "Comprobando conexión...");
  $("launchApp").classList.add("hidden");
  const status = await send({ action: "app_status" });
  if (!status.host) {
    setStatus("error", "No se puede conectar con Geas",
      `${status.error || ""} — Ejecuta register_host.bat en la carpeta de Geas y reinicia el navegador.`);
  } else if (status.appRunning) {
    setStatus("ok", "Geas está en ejecución");
  } else {
    setStatus("warn", "Geas está cerrado", "Se abrirá automáticamente al descargar.");
    $("launchApp").classList.remove("hidden");
  }
}

function formatSize(size) {
  return size ? ` • ${(size / (1024 * 1024)).toFixed(2)} MB` : "";
}

function describe(item) {
  const kinds = { hls: "HLS (m3u8)", dash: "DASH (mpd)" };
  return (kinds[item.kind] || item.contentType || "Video") + formatSize(item.size);
}

async function renderMedia() {
  const list = $("mediaList");
  list.replaceChildren();
  const response = currentTab ? await send({ action: "get_media", tabId: currentTab.id }) : { ok: false };
  const items = response.ok ? response.items : [];
  $("mediaTitle").textContent = `Medios detectados en esta pestaña (${items.length})`;

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Reproduce el video para que Geas detecte sus archivos.";
    list.appendChild(empty);
    return;
  }

  for (const item of items) {
    const row = document.createElement("div");
    row.className = "media-item";
    const info = document.createElement("div");
    info.className = "media-info";
    const name = document.createElement("div");
    name.className = "media-name";
    name.textContent = item.filename || "media";
    name.title = item.url;
    const meta = document.createElement("div");
    meta.className = "media-meta";
    meta.textContent = describe(item);
    info.append(name, meta);

    const btn = document.createElement("button");
    btn.textContent = "Descargar";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Enviando...";
      const result = await send({ action: "download_media", tabId: currentTab.id, key: item.key });
      btn.textContent = result.ok ? "✓ Enviado" : "Error";
      btn.title = result.ok ? "" : result.error || "";
      btn.disabled = result.ok;
    });
    row.append(info, btn);
    list.appendChild(row);
  }
}

async function init() {
  $("version").textContent = `v${api.runtime.getManifest().version}`;

  const settings = await api.storage.local.get(DEFAULT_SETTINGS);
  for (const key of Object.keys(DEFAULT_SETTINGS)) {
    const checkbox = $(key);
    checkbox.checked = settings[key];
    checkbox.addEventListener("change", () => api.storage.local.set({ [key]: checkbox.checked }));
  }

  [currentTab] = await api.tabs.query({ active: true, currentWindow: true });
  const pageButton = $("downloadPage");
  pageButton.disabled = !currentTab || !/^https?:/i.test(currentTab.url || "");
  pageButton.addEventListener("click", async () => {
    pageButton.disabled = true;
    pageButton.textContent = "Enviando...";
    const result = await send({ action: "download_page", tabId: currentTab.id });
    pageButton.textContent = result.ok ? "✓ Enviado a Geas" : `Error: ${result.error}`;
    pageButton.disabled = false;
  });

  $("launchApp").addEventListener("click", async () => {
    $("launchApp").disabled = true;
    $("launchApp").textContent = "Iniciando...";
    await send({ action: "launch_app" });
    $("launchApp").disabled = false;
    $("launchApp").textContent = "Iniciar Geas";
    refreshStatus();
  });

  renderMedia();
  refreshStatus();
}

init();
