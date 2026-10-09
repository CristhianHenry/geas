// Geas - script de contenido
//  - Botón "Descargar video" sobre cada <video> (también dentro de shadow DOM)
//  - Panel con los medios detectados en la pestaña (solo en el frame principal)
//  - Avisos breves enviados por el service worker
(() => {
  // Al recargar la extensión el script anterior sigue vivo en la página: se retira
  if (typeof window.__geasCleanup === "function") {
    try {
      window.__geasCleanup();
    } catch (e) {
      // El script anterior ya no tiene contexto de extensión; sus restos se quitan igual
    }
  }

  const IS_TOP = window.top === window;
  const MIN_VIDEO_WIDTH = 120;
  const MIN_VIDEO_HEIGHT = 68;
  const BUTTON_TEXT = "Descargar video";

  const activeVideos = new Map(); // video -> { btn, update }
  const intervals = [];
  let showButtons = true;
  let detectedMedia = [];
  let toggleBtn = null;
  let panel = null;
  let scanTimer = null;
  let ticking = false;

  // ------------------------------------------------------------------ utilidades

  function extensionAlive() {
    try {
      return Boolean(chrome.runtime && chrome.runtime.id);
    } catch (e) {
      return false;
    }
  }

  function sendMessage(message) {
    return new Promise((resolve) => {
      if (!extensionAlive()) {
        resolve({ ok: false, error: "La extensión se actualizó: recarga la página" });
        return;
      }
      try {
        chrome.runtime.sendMessage(message, (response) => {
          if (chrome.runtime.lastError) resolve({ ok: false, error: chrome.runtime.lastError.message });
          else resolve(response || { ok: false, error: "Sin respuesta de la extensión" });
        });
      } catch (e) {
        resolve({ ok: false, error: e.message });
      }
    });
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function stopPagePropagation(node) {
    // Evita que el reproductor o la página reaccionen a los clics en nuestros botones
    for (const type of ["mousedown", "mouseup", "pointerdown", "pointerup", "touchstart"]) {
      node.addEventListener(type, (e) => e.stopPropagation());
    }
  }

  function flash(btn, text, state, restoreText) {
    btn.textContent = text;
    btn.dataset.state = state;
    setTimeout(() => {
      if (!btn.isConnected) return;
      btn.textContent = restoreText;
      delete btn.dataset.state;
    }, 3000);
  }

  // ------------------------------------------------------------------ botón sobre los videos

  function shadowRootOf(node) {
    if (node.shadowRoot) return node.shadowRoot;
    // Las raíces cerradas solo pueden estar en elementos personalizados (con guion)
    if (!node.localName.includes("-")) return null;
    try {
      if (chrome.dom && chrome.dom.openOrClosedShadowRoot) return chrome.dom.openOrClosedShadowRoot(node);
      return node.openOrClosedShadowRoot || null; // Firefox: propiedad solo visible para extensiones
    } catch (e) {
      return null;
    }
  }

  function collectVideos(root, out) {
    for (const video of root.querySelectorAll("video")) out.push(video);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const shadow = shadowRootOf(node);
      if (shadow) collectVideos(shadow, out);
    }
    return out;
  }

  function videoSource(video) {
    const candidates = [video.currentSrc, video.src, ...Array.from(video.querySelectorAll("source"), (s) => s.src)];
    return candidates.find((src) => /^https?:/i.test(src || "")) || null;
  }

  function attachButton(video) {
    if (activeVideos.has(video) || !document.body) return;

    const btn = el("button", "geas-download-btn", BUTTON_TEXT);
    btn.type = "button";
    stopPagePropagation(btn);
    document.body.appendChild(btn);

    const update = () => {
      if (!video.isConnected || !showButtons) {
        btn.remove();
        activeVideos.delete(video);
        return;
      }
      const r = video.getBoundingClientRect();
      if (r.width < MIN_VIDEO_WIDTH || r.height < MIN_VIDEO_HEIGHT || r.bottom < 0 || r.top > window.innerHeight) {
        btn.style.display = "none";
        return;
      }
      btn.style.display = "flex";
      // Esquina superior derecha del video
      btn.style.top = `${window.scrollY + r.top}px`;
      btn.style.left = `${window.scrollX + Math.max(r.left, r.right - btn.offsetWidth)}px`;
    };

    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      btn.textContent = "⏳ Enviando...";
      const response = await sendMessage({
        action: "download_video",
        src: videoSource(video),
        pageUrl: location.href,
        title: document.title
      });
      btn.title = response.ok ? "" : response.error || "";
      flash(btn, response.ok ? "✓ Enviado a Geas" : "❌ Error", response.ok ? "ok" : "error", BUTTON_TEXT);
    });

    activeVideos.set(video, { btn, update });
    update();
  }

  function scanForVideos() {
    if (!showButtons || !document.body) return;
    for (const video of collectVideos(document, [])) attachButton(video);
  }

  function scheduleScan() {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(scanForVideos, 400);
  }

  function updateButtons() {
    activeVideos.forEach((holder) => holder.update());
  }

  function onScrollOrResize() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      updateButtons();
      ticking = false;
    });
  }

  // ------------------------------------------------------------------ panel de medios (frame principal)

  function describe(item) {
    const kinds = { hls: "HLS (m3u8)", dash: "DASH (mpd)" };
    let text = kinds[item.kind] || item.contentType || "Video";
    if (item.size) text += ` • ${(item.size / (1024 * 1024)).toFixed(2)} MB`;
    return text;
  }

  function shorten(text, max) {
    return text.length > max ? `${text.slice(0, max - 3)}...` : text;
  }

  function removeMediaUI() {
    if (toggleBtn) toggleBtn.remove();
    if (panel) panel.remove();
    toggleBtn = null;
    panel = null;
  }

  function renderPanelItems() {
    const body = panel.querySelector(".geas-panel-body");
    body.replaceChildren();
    for (const item of detectedMedia) {
      const row = el("div", "geas-panel-item");
      const info = el("div", "geas-panel-item-info");
      const name = el("div", "geas-panel-item-name", shorten(item.filename || "media", 40));
      name.title = item.url;
      info.append(name, el("div", "geas-panel-item-type", describe(item)));

      const btn = el("button", "geas-panel-item-btn", "Descargar");
      btn.type = "button";
      btn.addEventListener("click", async () => {
        btn.textContent = "Enviando...";
        btn.disabled = true;
        const response = await sendMessage({ action: "download_media", key: item.key });
        btn.disabled = false;
        btn.title = response.ok ? "" : response.error || "";
        flash(btn, response.ok ? "✓ Enviado" : "Error", response.ok ? "ok" : "error", "Descargar");
      });
      row.append(info, btn);
      body.appendChild(row);
    }
  }

  function createPanel() {
    panel = el("div", "geas-panel");
    const header = el("div", "geas-panel-header");
    const close = el("button", "geas-panel-close", "✕");
    close.type = "button";
    close.addEventListener("click", () => {
      panel.style.display = "none";
    });
    header.append(el("span", "", "📥 Geas - Medios detectados"), close);
    panel.append(header, el("div", "geas-panel-body"));
    stopPagePropagation(panel);
    document.body.appendChild(panel);
  }

  function togglePanel() {
    if (!panel) {
      createPanel();
    } else if (panel.style.display !== "none") {
      panel.style.display = "none";
      return;
    }
    panel.style.display = "block";
    renderPanelItems();
  }

  function renderMediaUI() {
    if (!IS_TOP || !document.body) return;
    if (!detectedMedia.length) {
      removeMediaUI();
      return;
    }
    if (!toggleBtn) {
      toggleBtn = el("button", "geas-download-btn geas-toggle-btn");
      toggleBtn.type = "button";
      toggleBtn.addEventListener("click", togglePanel);
      stopPagePropagation(toggleBtn);
      document.body.appendChild(toggleBtn);
    }
    toggleBtn.textContent = `📂 Medios (${detectedMedia.length})`;
    if (panel && panel.style.display !== "none") renderPanelItems();
  }

  // ------------------------------------------------------------------ avisos

  function showToast(text, isError) {
    if (!IS_TOP || !document.body) return;
    const toast = el("div", `geas-toast${isError ? " geas-toast-error" : ""}`, text);
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
  }

  // ------------------------------------------------------------------ mensajes y arranque

  function onMessage(request) {
    if (!request) return;
    if (request.action === "media_list" && IS_TOP) {
      detectedMedia = request.items || [];
      renderMediaUI();
    } else if (request.action === "toast") {
      showToast(request.text, request.error);
    }
  }

  function onStorageChange(changes, area) {
    if (area !== "local" || !changes.showVideoButtons) return;
    showButtons = changes.showVideoButtons.newValue !== false;
    if (showButtons) scanForVideos();
    else updateButtons(); // update() quita los botones si están desactivados
  }

  const observer = new MutationObserver(scheduleScan);

  function cleanup() {
    intervals.forEach(clearInterval);
    clearTimeout(scanTimer);
    observer.disconnect();
    document.removeEventListener("scroll", onScrollOrResize, true);
    window.removeEventListener("resize", onScrollOrResize);
    activeVideos.forEach(({ btn }) => btn.remove());
    activeVideos.clear();
    removeMediaUI();
    try {
      chrome.runtime.onMessage.removeListener(onMessage);
      chrome.storage.onChanged.removeListener(onStorageChange);
    } catch (e) {
      // Sin contexto de extensión no hay nada que quitar
    }
    if (window.__geasCleanup === cleanup) delete window.__geasCleanup;
  }
  window.__geasCleanup = cleanup;

  chrome.runtime.onMessage.addListener(onMessage);
  chrome.storage.onChanged.addListener(onStorageChange);
  chrome.storage.local.get({ showVideoButtons: true }, (settings) => {
    showButtons = !chrome.runtime.lastError && settings.showVideoButtons !== false;
    scanForVideos();
  });

  // scroll en captura: también llegan los de contenedores con scroll propio
  document.addEventListener("scroll", onScrollOrResize, { capture: true, passive: true });
  window.addEventListener("resize", onScrollOrResize, { passive: true });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  intervals.push(setInterval(() => {
    if (!extensionAlive()) {
      cleanup();
      return;
    }
    updateButtons(); // posiciones y limpieza de videos eliminados
  }, 1000));
  // Los cambios dentro de shadow DOM no los ve el MutationObserver
  intervals.push(setInterval(scanForVideos, 3000));

  if (IS_TOP) {
    sendMessage({ action: "get_media" }).then((response) => {
      if (response.ok) {
        detectedMedia = response.items || [];
        renderMediaUI();
      }
    });
  }
})();
