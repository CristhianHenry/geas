// Geas - service worker de la extensión
//  - Detecta medios (MP4, HLS, DASH...) en el tráfico de cada pestaña.
//  - Captura las descargas del navegador y las entrega a Geas (como IDM).
//  - Junto con cada descarga envía cookies, Referer y User-Agent del navegador:
//    sin ellos muchos servidores responden 403 o entregan otra cosa.
import { DEFAULT_SETTINGS } from "./settings.js";

const HOST_NAME = "com.geas.host";

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

function isHttpUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url);
}

function parseUrl(url) {
  try {
    return new URL(url);
  } catch (e) {
    return null;
  }
}

function baseName(path) {
  const name = (path || "").split(/[\\/]/).pop() || "";
  try {
    return decodeURIComponent(name);
  } catch (e) {
    return name;
  }
}

function urlFileName(url) {
  const parsed = parseUrl(url);
  return parsed ? baseName(parsed.pathname) : "";
}

function extensionOf(name) {
  const match = /\.([a-z0-9]{1,5})$/i.exec(name || "");
  return match ? match[1].toLowerCase() : "";
}

function canonicalHeader(name) {
  return name.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join("-");
}

function headerValue(headers, name) {
  const found = (headers || []).find((h) => h.name.toLowerCase() === name);
  return found ? found.value : null;
}

function sanitizeFileName(name) {
  return (name || "").replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").replace(/\s+/g, " ").trim().slice(0, 150);
}

async function getSettings() {
  try {
    return await chrome.storage.local.get(DEFAULT_SETTINGS);
  } catch (e) {
    return { ...DEFAULT_SETTINGS };
  }
}

// ---------------------------------------------------------------------------
// Comunicación con Geas (Native Messaging)
// ---------------------------------------------------------------------------

async function sendToApp(message) {
  try {
    const response = await chrome.runtime.sendNativeMessage(HOST_NAME, message);
    if (response && response.status === "success") return { ...response, ok: true };
    return { ok: false, error: (response && response.text) || "Respuesta inválida del host nativo" };
  } catch (err) {
    return { ok: false, error: (err && err.message) || String(err) };
  }
}

async function appStatus() {
  const result = await sendToApp({ action: "ping" });
  if (!result.ok) return { ok: true, host: false, appRunning: false, error: result.error };
  return { ok: true, host: true, appRunning: Boolean(result.app_running) };
}

async function collectCookies(urls) {
  const cookies = new Map();
  for (const url of new Set(urls.filter(isHttpUrl))) {
    try {
      for (const c of await chrome.cookies.getAll({ url })) {
        cookies.set(`${c.domain}|${c.path}|${c.name}`, {
          name: c.name,
          value: c.value,
          domain: c.domain,
          path: c.path,
          secure: c.secure,
          httpOnly: c.httpOnly,
          hostOnly: c.hostOnly,
          expirationDate: c.session ? null : c.expirationDate
        });
      }
    } catch (e) {
      // Sin acceso a las cookies de ese sitio: la descarga se envía sin ellas
    }
  }
  return [...cookies.values()];
}

function toStreamPayload(entry) {
  return {
    url: entry.url,
    kind: entry.kind,
    size: entry.size || null,
    headers: entry.headers || {},
    segment_url: entry.segmentUrl || null,
    segment_headers: entry.segmentHeaders || {}
  };
}

async function buildPayload({ kind, url, filename, size, pageUrl, topUrl, title, referer, headers, streams = [], hostHeaders = {}, cookieUrls = [] }) {
  return {
    action: "download",
    extension_version: chrome.runtime.getManifest().version,
    kind,
    url,
    filename: filename || null,
    size: size || null,
    page_url: pageUrl || null,
    top_url: topUrl || null,
    title: title || null,
    referer: referer || null,
    user_agent: navigator.userAgent,
    headers: headers || {},
    streams: streams.map(toStreamPayload),
    host_headers: hostHeaders,
    cookies: await collectCookies([url, pageUrl, topUrl, ...streams.flatMap((s) => [s.url, s.segmentUrl]), ...cookieUrls])
  };
}

// Avisos dentro de la página (los muestra content.js en el frame principal)
function notifyTab(tabId, text, error = false) {
  if (typeof tabId !== "number" || tabId < 0) return;
  chrome.tabs.sendMessage(tabId, { action: "toast", text, error }, { frameId: 0 }).catch(() => {});
}

async function notifyActiveTab(text, error = false) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tab) notifyTab(tab.id, text, error);
  } catch (e) {
    // Sin pestaña activa (por ejemplo, ventana de descargas): no hay dónde avisar
  }
}

// ---------------------------------------------------------------------------
// Medios detectados por pestaña
// ---------------------------------------------------------------------------
// Se guardan también en chrome.storage.session: el service worker se detiene
// tras unos segundos sin actividad y perdería lo que tiene en memoria.

const MAX_MEDIA_PER_TAB = 30;
const tabMedia = new Map(); // tabId -> entradas (la más reciente primero)
let restorePromise = null;
let persistTimer = null;

function restoreMedia() {
  if (!restorePromise) {
    restorePromise = chrome.storage.session.get("tabMedia").then((data) => {
      for (const [tabId, items] of Object.entries(data.tabMedia || {})) {
        if (!tabMedia.has(Number(tabId))) tabMedia.set(Number(tabId), items);
      }
    }).catch(() => {});
  }
  return restorePromise;
}

function persistMedia() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    chrome.storage.session.set({ tabMedia: Object.fromEntries(tabMedia) }).catch(() => {});
  }, 250);
}

async function getTabMedia(tabId) {
  await restoreMedia();
  return tabMedia.get(tabId) || [];
}

function publicItems(items) {
  // Las cabeceras capturadas (pueden llevar tokens) no se pasan a la página
  return items.map(({ key, url, kind, size, contentType, filename }) => ({ key, url, kind, size, contentType, filename }));
}

function updateBadge(tabId, count) {
  chrome.action.setBadgeText({ tabId, text: count ? String(count) : "" }).catch(() => {});
}

async function addMedia(tabId, entry) {
  await restoreMedia();
  const items = tabMedia.get(tabId) || [];
  const index = items.findIndex((item) => item.key === entry.key);
  if (index >= 0) {
    entry.size = entry.size || items[index].size;
    items.splice(index, 1);
  }
  items.unshift(entry);
  items.length = Math.min(items.length, MAX_MEDIA_PER_TAB);
  tabMedia.set(tabId, items);
  persistMedia();
  updateBadge(tabId, items.length);
  if (index < 0) {
    chrome.tabs.sendMessage(tabId, { action: "media_list", items: publicItems(items) }, { frameId: 0 }).catch(() => {});
  }
}

// El servidor de los fragmentos puede exigir otras cabeceras que el de la lista
// (por ejemplo, rechazar lo que parece una navegación): se guardan las del primer
// fragmento que pidió el reproductor junto a las listas HLS/DASH de ese frame.
async function attachSegmentHeaders(tabId, frameId, url, headers) {
  await restoreMedia();
  const streams = (tabMedia.get(tabId) || []).filter((item) => item.kind === "hls" || item.kind === "dash");
  const sameFrame = streams.filter((item) => item.frameId === frameId);
  let changed = false;
  for (const item of sameFrame.length ? sameFrame : streams) {
    if (!item.segmentUrl) {
      item.segmentUrl = url;
      item.segmentHeaders = headers;
      changed = true;
    }
  }
  if (changed) persistMedia();
}

// Últimas cabeceras que usó la pestaña con cada servidor (sin las de APIs, HTML, JS...).
// Si los fragmentos van disfrazados (de imagen, por ejemplo) y no se reconocen,
// Geas toma las del servidor donde estén. Solo en memoria: mientras se reproduce
// el video, las peticiones mantienen vivo el service worker.
const MAX_HOSTS_PER_TAB = 20;
const NON_MEDIA_TYPES = /^(application\/(json|javascript|x-javascript|xml)|text\/(html|css|javascript|xml))/;
const tabHosts = new Map(); // tabId -> Map(servidor -> cabeceras)

function rememberHostHeaders(details, headers) {
  if (!Object.keys(headers).length) return;
  const contentType = (headerValue(details.responseHeaders, "content-type") || "").toLowerCase();
  const parsed = parseUrl(details.url);
  if (!parsed || NON_MEDIA_TYPES.test(contentType)) return;
  const hosts = tabHosts.get(details.tabId) || new Map();
  hosts.delete(parsed.host);
  hosts.set(parsed.host, headers);
  if (hosts.size > MAX_HOSTS_PER_TAB) hosts.delete(hosts.keys().next().value);
  tabHosts.set(details.tabId, hosts);
}

function hostHeadersFor(tabId) {
  return Object.fromEntries(tabHosts.get(tabId) || []);
}

async function clearTabMedia(tabId) {
  tabHosts.delete(tabId);
  await restoreMedia();
  if (tabMedia.delete(tabId)) persistMedia();
  updateBadge(tabId, 0);
}

// ---------------------------------------------------------------------------
// Detector de medios (tráfico de red)
// ---------------------------------------------------------------------------

const HTTP_URLS = ["http://*/*", "https://*/*"];
const SNIFF_FILTER = {
  urls: HTTP_URLS,
  types: ["main_frame", "sub_frame", "media", "xmlhttprequest", "object", "other"]
};
const HLS_TYPES = new Set(["application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "audio/x-mpegurl"]);
const DASH_TYPES = new Set(["application/dash+xml"]);
const SEGMENT_TYPES = new Set(["video/mp2t", "video/iso.segment", "audio/iso.segment"]);
const GENERIC_TYPES = new Set(["", "application/octet-stream", "binary/octet-stream", "application/force-download"]);
const MEDIA_EXTENSIONS = new Set([
  "mp4", "m4v", "webm", "mkv", "mov", "avi", "flv", "wmv", "3gp", "ogv",
  "mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac", "wma"
]);
const MIN_MEDIA_SIZE = 1024 * 1024; // Ignora miniaturas, sonidos cortos y fragmentos
// Peticiones parciales de un video: el video completo se obtiene desde la página (yt-dlp)
const IGNORE_URL_PATTERNS = [
  /[?&](range|bytestart|byteend)=/i,
  /googlevideo\.com\/videoplayback/i,
  /\/range\//i
];
// Fragmentos de HLS/DASH: lo útil es su lista de reproducción (.m3u8 / .mpd)
const SEGMENT_NAME = /(\.(ts|m4s|m4f|cmfv|cmfa)$)|^(seg|segment|chunk|frag|fragment)[-_]?\d+/i;
// Cabeceras que se repiten al descargar (las cookies van aparte; Range, Host, etc. no)
const CAPTURED_HEADERS = new Set(["referer", "origin", "authorization", "accept", "accept-language", "user-agent"]);
const CAPTURED_PREFIXES = ["x-", "sec-fetch-", "sec-ch-"];
const SKIPPED_HEADERS = new Set(["x-client-data"]);

const requestHeaders = new Map(); // requestId -> cabeceras útiles que envió el navegador

function pickRequestHeaders(headers) {
  const picked = {};
  for (const { name, value } of headers || []) {
    const lower = name.toLowerCase();
    if (typeof value !== "string" || SKIPPED_HEADERS.has(lower)) continue;
    if (CAPTURED_HEADERS.has(lower) || CAPTURED_PREFIXES.some((prefix) => lower.startsWith(prefix))) {
      picked[canonicalHeader(lower)] = value;
    }
  }
  return picked;
}

function totalSize(statusCode, headers) {
  if (statusCode === 206) {
    // "bytes 0-1023/52428800": el total es lo que pesa el archivo completo
    const match = /\/(\d+)\s*$/.exec(headerValue(headers, "content-range") || "");
    return match ? Number(match[1]) : null;
  }
  const length = headerValue(headers, "content-length");
  return length && /^\d+$/.test(length) ? Number(length) : null;
}

function classifyResponse(details) {
  if (IGNORE_URL_PATTERNS.some((pattern) => pattern.test(details.url))) return null;
  const parsed = parseUrl(details.url);
  if (!parsed) return null;
  const name = baseName(parsed.pathname);
  const ext = extensionOf(name);
  const contentType = (headerValue(details.responseHeaders, "content-type") || "").split(";")[0].trim().toLowerCase();

  // Listas de reproducción: siempre interesan, aunque pesen pocos KB
  if (HLS_TYPES.has(contentType) || ext === "m3u8") return { kind: "hls", contentType, size: null, name };
  if (DASH_TYPES.has(contentType) || ext === "mpd") return { kind: "dash", contentType, size: null, name };

  if (SEGMENT_TYPES.has(contentType) || SEGMENT_NAME.test(name)) return { kind: "segment" };
  const isMediaType = contentType.startsWith("video/") || contentType.startsWith("audio/");
  if (!isMediaType && !(MEDIA_EXTENSIONS.has(ext) && GENERIC_TYPES.has(contentType))) return null;

  const size = totalSize(details.statusCode, details.responseHeaders);
  if (size !== null && size < MIN_MEDIA_SIZE) return null;
  return { kind: "file", contentType, size, name };
}

chrome.webRequest.onSendHeaders.addListener((details) => {
  if (details.tabId < 0) return;
  const picked = pickRequestHeaders(details.requestHeaders);
  if (Object.keys(picked).length) requestHeaders.set(details.requestId, picked);
}, SNIFF_FILTER, ["requestHeaders", "extraHeaders"]);

chrome.webRequest.onHeadersReceived.addListener((details) => {
  const headers = requestHeaders.get(details.requestId) || {};
  requestHeaders.delete(details.requestId);
  if (details.tabId < 0 || (details.statusCode !== 200 && details.statusCode !== 206)) return;
  if (details.type === "media" || details.type === "xmlhttprequest" || details.type === "other") {
    rememberHostHeaders(details, headers);
  }

  const media = classifyResponse(details);
  if (!media) return;
  if (media.kind === "segment") {
    attachSegmentHeaders(details.tabId, details.frameId, details.url, headers).catch(() => {});
    return;
  }
  const parsed = new URL(details.url);
  addMedia(details.tabId, {
    key: parsed.origin + parsed.pathname, // la misma lista con otro token no se repite
    url: details.url,
    kind: media.kind,
    contentType: media.contentType,
    size: media.size,
    filename: media.name,
    headers,
    frameId: details.frameId,
    time: Date.now()
  }).catch(() => {});
}, SNIFF_FILTER, ["responseHeaders"]);

const forgetRequest = (details) => requestHeaders.delete(details.requestId);
chrome.webRequest.onCompleted.addListener(forgetRequest, SNIFF_FILTER);
chrome.webRequest.onErrorOccurred.addListener(forgetRequest, SNIFF_FILTER);

// Al cambiar de página se vacía la lista (las descargas no cuentan como navegación)
chrome.webNavigation.onCommitted.addListener((details) => {
  if (details.frameId === 0) clearTabMedia(details.tabId);
});
chrome.tabs.onRemoved.addListener((tabId) => {
  clearTabMedia(tabId);
});

// Respuestas a formularios POST: no se pueden repetir fuera del navegador
const postNavigations = new Map(); // url -> momento del POST
chrome.webRequest.onBeforeRequest.addListener((details) => {
  if (details.method !== "POST") return;
  const now = Date.now();
  postNavigations.set(details.url, now);
  for (const [url, time] of postNavigations) {
    if (now - time > 120000) postNavigations.delete(url);
  }
}, { urls: HTTP_URLS, types: ["main_frame", "sub_frame"] });

// ---------------------------------------------------------------------------
// Envío de videos y medios detectados
// ---------------------------------------------------------------------------

const TYPE_EXTENSIONS = {
  "video/mp4": "mp4", "video/webm": "webm", "video/x-matroska": "mkv", "video/quicktime": "mov",
  "video/x-flv": "flv", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac",
  "audio/ogg": "ogg", "audio/webm": "weba", "audio/wav": "wav", "audio/x-wav": "wav", "audio/flac": "flac"
};

function mediaFileName(entry, pageTitle) {
  const ext = extensionOf(entry.filename) || TYPE_EXTENSIONS[entry.contentType] || "mp4";
  const title = sanitizeFileName(pageTitle);
  return title ? `${title}.${ext}` : entry.filename || `video.${ext}`;
}

// Video de una página: Geas prueba la página con yt-dlp y, si no sirve,
// los streams que se detectaron en la pestaña.
async function requestVideo({ tab, frameId = 0, frameUrl, src = null, title = null }) {
  if (!tab || !isHttpUrl(tab.url)) return { ok: false, error: "Esta página no se puede analizar" };
  const topUrl = tab.url;
  const pageUrl = isHttpUrl(frameUrl) ? frameUrl : topUrl;
  // Primero los medios del mismo frame que el video (dentro de cada grupo, los más recientes)
  const streams = [...(await getTabMedia(tab.id))].sort((a, b) => (b.frameId === frameId) - (a.frameId === frameId));
  if (isHttpUrl(src) && !streams.some((s) => s.url === src)) {
    const ext = extensionOf(urlFileName(src));
    const kind = ext === "m3u8" ? "hls" : ext === "mpd" ? "dash" : "file";
    streams.unshift({ url: src, kind, size: null, headers: { Referer: pageUrl } });
  }
  return sendToApp(await buildPayload({
    kind: "video",
    url: pageUrl,
    pageUrl,
    topUrl,
    title: tab.title || title,
    referer: pageUrl !== topUrl ? topUrl : null,
    streams,
    hostHeaders: hostHeadersFor(tab.id)
  }));
}

async function downloadMediaEntry(tabId, key) {
  const items = await getTabMedia(tabId);
  const entry = items.find((item) => item.key === key);
  if (!entry) return { ok: false, error: "El medio ya no está disponible; recarga la página" };
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  const topUrl = tab ? tab.url : null;
  const title = tab ? tab.title : null;

  if (entry.kind === "file") {
    // Archivo completo (MP4, MP3...): descarga directa multi-hilo
    return sendToApp(await buildPayload({
      kind: "file",
      url: entry.url,
      filename: mediaFileName(entry, title),
      size: entry.size,
      pageUrl: topUrl,
      topUrl,
      title,
      referer: entry.headers.Referer || topUrl,
      headers: entry.headers
    }));
  }
  // HLS / DASH: Geas lo analiza con yt-dlp para elegir la calidad
  return sendToApp(await buildPayload({
    kind: "stream",
    url: entry.url,
    pageUrl: topUrl,
    topUrl,
    title,
    streams: [entry, ...items.filter((item) => item !== entry)],
    hostHeaders: hostHeadersFor(tabId)
  }));
}

// ---------------------------------------------------------------------------
// Captura de descargas del navegador (como IDM)
// ---------------------------------------------------------------------------

const INTERCEPT_EXTENSIONS = new Set([
  "3gp", "7z", "aac", "ace", "aif", "apk", "arj", "asf", "avi", "bin", "bz2", "cab", "deb", "dmg",
  "doc", "docx", "epub", "exe", "flac", "flv", "gz", "img", "iso", "jar", "lzh", "m4a", "m4v",
  "mkv", "mov", "mp3", "mp4", "mpeg", "mpg", "msi", "msix", "msu", "ogg", "ogv", "opus", "pdf",
  "pkg", "ppt", "pptx", "rar", "rm", "rmvb", "rpm", "tar", "tgz", "wav", "webm", "wma", "wmv",
  "xls", "xlsx", "xz", "zip", "zst"
]);
const INTERCEPT_MIMES = new Set([
  "application/octet-stream", "application/zip", "application/x-zip-compressed",
  "application/x-rar-compressed", "application/vnd.rar", "application/x-7z-compressed",
  "application/x-msdownload", "application/x-msi", "application/x-iso9660-image",
  "application/x-tar", "application/gzip", "application/x-gzip", "application/x-bzip2",
  "application/x-xz", "application/vnd.android.package-archive", "application/x-apple-diskimage",
  "application/pdf", "application/java-archive"
]);

function shouldIntercept(item) {
  // Las descargas iniciadas por extensiones (incluida esta, al devolverle una) siguen en el navegador
  if (item.byExtensionId || item.incognito) return false;
  const url = item.finalUrl || item.url;
  if (!isHttpUrl(url)) return false; // blob:, data:, file: solo existen dentro del navegador
  if (postNavigations.has(item.url) || postNavigations.has(url)) return false;
  const ext = extensionOf(baseName(item.filename) || urlFileName(url));
  if (ext) return INTERCEPT_EXTENSIONS.has(ext);
  // Sin extensión: decide el tipo MIME
  const mime = (item.mime || "").toLowerCase();
  return (mime.startsWith("video/") || mime.startsWith("audio/") || INTERCEPT_MIMES.has(mime)) && !HLS_TYPES.has(mime);
}

async function interceptDownload(item) {
  const settings = await getSettings();
  if (!settings.interceptDownloads || !shouldIntercept(item)) return false;

  await chrome.downloads.cancel(item.id).catch(() => {});
  chrome.downloads.erase({ id: item.id }).catch(() => {});

  const url = item.finalUrl || item.url;
  const result = await sendToApp(await buildPayload({
    kind: "file",
    url,
    filename: baseName(item.filename) || urlFileName(url) || null,
    size: item.totalBytes > 0 ? item.totalBytes : null,
    pageUrl: item.referrer || null,
    referer: item.referrer || null
  }));

  if (result.ok) {
    notifyActiveTab("Descarga enviada a Geas");
  } else {
    // Geas no está disponible: la descarga vuelve al navegador
    chrome.downloads.download({ url: item.url }).catch(() => {});
    notifyActiveTab(`Geas no respondió (${result.error}). La descarga continúa en el navegador.`, true);
  }
  return true;
}

chrome.downloads.onDeterminingFilename.addListener((item, suggest) => {
  interceptDownload(item).then((captured) => {
    if (!captured) suggest();
  }, () => suggest());
  return true; // suggest() se llama de forma asíncrona
});

// ---------------------------------------------------------------------------
// Menú contextual
// ---------------------------------------------------------------------------

const FILE_EXTENSIONS = new Set([
  ...INTERCEPT_EXTENSIONS, ...MEDIA_EXTENSIONS,
  "jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "txt", "csv", "json", "xml", "torrent"
]);

function guessLinkKind(url) {
  const ext = extensionOf(urlFileName(url));
  if (ext === "m3u8" || ext === "mpd") return "stream";
  if (FILE_EXTENSIONS.has(ext)) return "file";
  return "auto"; // Geas consulta la URL: si es una página busca el video, si no la descarga
}

// Se ejecuta dentro de la página: los enlaces http(s) del documento (o solo los de la selección)
function collectPageLinks(selectionOnly) {
  let anchors = [...document.querySelectorAll("a[href]")];
  const selection = window.getSelection();
  if (selectionOnly && selection && selection.rangeCount) {
    anchors = anchors.filter((a) => selection.containsNode(a, true));
  }
  const seen = new Set();
  const links = [];
  for (const a of anchors) {
    const url = a.href;
    if (!/^https?:/i.test(url) || seen.has(url)) continue;
    seen.add(url);
    links.push({ url, text: (a.textContent || a.title || "").trim().replace(/\s+/g, " ").slice(0, 200) });
    if (links.length >= 5000) break;
  }
  return links;
}

async function requestAllLinks(info, tab) {
  const frameUrl = info.frameUrl || info.pageUrl || tab.url;
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [info.frameId || 0] },
    func: collectPageLinks,
    args: [info.menuItemId === "geas_selection_links"]
  });
  const links = (injection && injection.result) || [];
  if (!links.length) return { ok: false, error: "no se encontraron enlaces" };
  // Las cookies de cada sitio enlazado (no de cada enlace: puede haber miles)
  const origins = [...new Set(links.map((link) => new URL(link.url).origin))].slice(0, 50);
  return sendToApp({
    ...(await buildPayload({
      kind: "links",
      url: frameUrl,
      pageUrl: frameUrl,
      topUrl: tab.url,
      title: tab.title,
      referer: frameUrl,
      cookieUrls: origins.map((origin) => origin + "/")
    })),
    links
  });
}

async function handleContextMenu(info, tab) {
  const tabId = tab ? tab.id : -1;
  const frameUrl = info.frameUrl || info.pageUrl || (tab && tab.url);
  let result;

  if (info.menuItemId === "geas_all_links" || info.menuItemId === "geas_selection_links") {
    if (!tab || !isHttpUrl(tab.url)) {
      notifyTab(tabId, "Geas: en esta página no se pueden leer los enlaces", true);
      return;
    }
    result = await requestAllLinks(info, tab);
  } else if (info.menuItemId === "geas_page_video" || info.mediaType === "video" || info.mediaType === "audio") {
    const src = info.menuItemId === "geas_page_video" ? null : info.srcUrl;
    result = await requestVideo({ tab, frameId: info.frameId || 0, frameUrl, src });
  } else {
    const url = info.linkUrl || info.srcUrl;
    if (!isHttpUrl(url)) {
      notifyTab(tabId, "Geas: este enlace solo existe dentro del navegador y no se puede descargar", true);
      return;
    }
    result = await sendToApp(await buildPayload({
      kind: info.linkUrl ? guessLinkKind(url) : "file",
      url,
      filename: urlFileName(url) || null,
      pageUrl: frameUrl,
      topUrl: tab && tab.url,
      title: tab && tab.title,
      referer: frameUrl
    }));
  }
  notifyTab(tabId, result.ok ? "Enviado a Geas" : `Geas: ${result.error}`, !result.ok);
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  handleContextMenu(info, tab).catch((err) => notifyTab(tab && tab.id, `Geas: ${err.message || err}`, true));
});

// ---------------------------------------------------------------------------
// Instalación
// ---------------------------------------------------------------------------

async function injectIntoOpenTabs() {
  // Las pestañas abiertas antes de instalar/actualizar no tienen el script de contenido
  const tabs = await chrome.tabs.query({ url: HTTP_URLS }).catch(() => []);
  for (const tab of tabs) {
    const target = { tabId: tab.id, allFrames: true };
    chrome.scripting.insertCSS({ target, files: ["content.css"] }).catch(() => {});
    chrome.scripting.executeScript({ target, files: ["content.js"] }).catch(() => {});
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "geas_download",
      title: "Descargar con Geas",
      contexts: ["link", "video", "audio", "image"]
    });
    chrome.contextMenus.create({
      id: "geas_page_video",
      title: "Descargar video de esta página con Geas",
      contexts: ["page", "frame"]
    });
    chrome.contextMenus.create({
      id: "geas_all_links",
      title: "Descargar todos los enlaces con Geas",
      contexts: ["page", "frame"]
    });
    chrome.contextMenus.create({
      id: "geas_selection_links",
      title: "Descargar los enlaces seleccionados con Geas",
      contexts: ["selection"]
    });
  });
  injectIntoOpenTabs();
});

// ---------------------------------------------------------------------------
// Mensajes de content.js y del popup
// ---------------------------------------------------------------------------

const MESSAGE_HANDLERS = {
  get_media: async (msg, sender) => ({ ok: true, items: publicItems(await getTabMedia(msg.tabId ?? sender.tab?.id)) }),
  download_media: (msg, sender) => downloadMediaEntry(msg.tabId ?? sender.tab?.id, msg.key),
  download_video: (msg, sender) => requestVideo({
    tab: sender.tab,
    frameId: sender.frameId,
    frameUrl: msg.pageUrl || sender.url,
    src: msg.src,
    title: msg.title
  }),
  download_page: async (msg) => requestVideo({ tab: await chrome.tabs.get(msg.tabId) }),
  app_status: () => appStatus(),
  launch_app: () => sendToApp({ action: "launch" })
};

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const handler = msg && MESSAGE_HANDLERS[msg.action];
  if (!handler) return false;
  Promise.resolve()
    .then(() => handler(msg, sender))
    .then(sendResponse, (err) => sendResponse({ ok: false, error: (err && err.message) || String(err) }));
  return true; // respuesta asíncrona
});

chrome.action.setBadgeBackgroundColor({ color: "#2196F3" }).catch(() => {});
restoreMedia();
