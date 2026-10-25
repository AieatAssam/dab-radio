/* Hallmark · component: listening mini-player · genre: atmospheric · theme: Workbench
 * states: default · hover · focus · active · disabled · loading · error · success
 * contrast: token-driven
 */
(() => {
  const parent = window;
  const origin = new URL(".", document.currentScript?.src || location.href).origin;
  const css = ["/tokens.css", "/fonts.css", "/mini-player.css"];
  const markup = `<main class="mini" aria-label="DAB mini-player">
    <header class="mini__head"><span class="mini__brand">DAB<span> / </span>RADIO</span><span class="mini__pin" title="Popup window">POPUP</span></header>
    <button class="mini__visual" type="button" aria-label="Change visualisation" title="Click or press Enter to change visualisation"><canvas></canvas><span class="mini__visual-hint">LED SPECTRUM · CLICK TO CHANGE</span></button>
    <section class="mini__track"><div class="mini__station"></div><div class="mini__title"></div><div class="mini__artist"></div><div class="mini__text"></div></section>
    <div class="mini__controls"><button data-action="previous" aria-label="Previous station" title="Previous">|◀</button><button data-action="play" aria-label="Play" title="Play">▶</button><button data-action="stop" aria-label="Stop" title="Stop">■</button><button data-action="next" aria-label="Next station" title="Next">▶|</button><button data-action="mute" aria-label="Mute" title="Mute">◖))</button><input data-action="volume" type="range" min="0" max="1" step="0.01" aria-label="Volume"></div>
    <div class="mini__error" role="status" hidden></div>
  </main>`;

  function create(adapter) {
    if (!adapter || typeof adapter.snapshot !== "function") throw new TypeError("DABMiniPlayer requires adapter.snapshot().");
    let target = null, visual = null, raf = 0, disposed = false, requested = false, lastRefresh = 0, openerPagehide = null, childCleanup = null, opening = null;
    let nativePiP = "documentPictureInPicture" in parent && parent.isSecureContext;
    function open() {
      if (disposed) return Promise.resolve(null);
      requested = true;
      if (target && !target.closed) { target.focus?.(); return Promise.resolve(target); }
      if (opening) return opening;
      if (nativePiP) {
        try {
          opening = parent.documentPictureInPicture.requestWindow({ width: 400, height: 260 })
            .then(win => mount(win, true))
            .catch(() => { nativePiP = false; return fallback(); })
            .finally(() => { opening = null; });
          return opening;
        } catch (_) { nativePiP = false; return Promise.resolve(fallback()); }
      }
      return Promise.resolve(fallback());
    }
    function fallback() {
      if (!requested || disposed) return null;
      let win;
      try { win = parent.open("about:blank", "dab-mini-player", "popup=yes,width=400,height=260,resizable=yes"); } catch (_) {}
      if (!win) { adapter.onError?.("The mini-player window was blocked. Try again, or allow pop-ups for this site."); return null; }
      return mount(win, false);
    }
    function mount(win, isPiP) {
      target = win;
      const doc = win.document;
      doc.documentElement.lang = "en";
      doc.head.replaceChildren();
      const meta = doc.createElement("meta"); meta.name = "viewport"; meta.content = "width=device-width,initial-scale=1";
      const title = doc.createElement("title"); title.textContent = "DAB Mini Player";
      doc.head.append(meta, title);
      const linksReady = Promise.all(css.map(href => new Promise(resolve => {
        const link = doc.createElement("link"); link.rel = "stylesheet"; link.href = `${origin}${href}`;
        let done = false; const finish = () => { if (!done) { done = true; resolve(); } };
        link.onload = finish; link.onerror = finish; win.setTimeout(finish, 1800); doc.head.append(link);
      })));
      doc.body.replaceChildren(); doc.body.innerHTML = markup;
      const q = s => doc.querySelector(s), canvas = q("canvas");
      const pin = q(".mini__pin"); pin.textContent = isPiP ? "PINNED · NATIVE PiP" : "POPUP WINDOW";
      pin.title = isPiP ? "Native Document Picture-in-Picture window" : "Normal popup. Use your desktop window controls to keep it on top, if supported.";
      q(".mini__visual").addEventListener("click", () => visual?.nextMode?.());
      doc.querySelectorAll("[data-action]").forEach(btn => btn.addEventListener("click", async () => {
        clearError();
        try {
          const state = adapter.snapshot() || {};
          if (btn.dataset.action === "play" && !state.playing) await adapter.play?.();
          if (btn.dataset.action === "stop") adapter.stop?.();
          if (btn.dataset.action === "previous") await adapter.previous?.();
          if (btn.dataset.action === "next") await adapter.next?.();
          if (btn.dataset.action === "mute") adapter.toggleMute?.();
          refresh(true);
        } catch (error) { showError(error?.message || "Playback action failed."); }
      }));
      q('[data-action="volume"]').addEventListener("input", e => { clearError(); try { adapter.setVolume?.(Number(e.target.value)); refresh(true); } catch (error) { showError(error?.message); } });
      // The visualisation API belongs to the opener, not the blank child window.
      try {
        let savedIndex = 0;
        try { savedIndex = Number(parent.localStorage.getItem("dab-mini-visual-index")) || 0; } catch (_) {}
        visual = parent.DABVisualisations?.create(canvas, {
          getAnalyser: () => adapter.getAnalyser?.() || null,
          isPlaying: () => !!adapter.snapshot().playing,
          mode: savedIndex,
          onModeChange: (_name, index) => { try { parent.localStorage.setItem("dab-mini-visual-index", String(index)); } catch (_) {} updateModeLabel(); }
        }) || null;
      } catch (_) { visual = null; }
      function updateModeLabel() { const hint = q(".mini__visual-hint"); if (hint) setText(hint, `${visual?.modeName || "SPECTRUM"} · CLICK TO CHANGE`); }
      let cleaned = false;
      function cleanup() {
        if (cleaned || target !== win) return;
        cleaned = true;
        if (raf) win.cancelAnimationFrame(raf); raf = 0;
        visual?.destroy?.(); visual = null;
        if (target === win) target = null;
        childCleanup = null;
      }
      childCleanup = cleanup;
      win.addEventListener("pagehide", cleanup, { once: true });
      win.addEventListener("beforeunload", cleanup, { once: true });
      if (!openerPagehide) { openerPagehide = () => close(); parent.addEventListener("pagehide", openerPagehide); }
      linksReady.then(() => { if (target === win) { refresh(true); updateModeLabel(); } });
      refresh(true);
      let last = 0;
      const draw = now => {
        if (target !== win || win.closed || !requested) return;
        if (now - last >= 200) { last = now; refresh(); }
        raf = win.requestAnimationFrame(draw);
      };
      raf = win.requestAnimationFrame(draw);
      return win;
    }
    function setText(el, value) { const next = value == null ? "" : String(value); if (el && el.textContent !== next) el.textContent = next; }
    function showError(message) { if (target && !target.closed) { const el = target.document.querySelector(".mini__error"); if (el) { el.hidden = false; setText(el, message || "Something went wrong."); } } }
    function clearError() { if (target && !target.closed) { const el = target.document.querySelector(".mini__error"); if (el) { el.hidden = true; setText(el, ""); } } }
    function refresh(force = false) {
      if (!target || target.closed) return;
      const now = performance.now(); if (!force && now - lastRefresh < 190) return; lastRefresh = now;
      const doc = target.document, state = adapter.snapshot() || {}, put = (sel, value) => setText(doc.querySelector(sel), value);
      put(".mini__station", state.station || "DAB RADIO");
      const trackTitle = state.title || state.radioText || "Waiting for broadcast text…";
      put(".mini__title", trackTitle);
      const titleNode = doc.querySelector(".mini__title");
      if (titleNode && titleNode.title !== trackTitle) titleNode.title = trackTitle;
      put(".mini__artist", state.artist || "");
      const textNode = doc.querySelector(".mini__text"), radioText = state.radioText || "";
      if (textNode) { textNode.hidden = !!radioText && radioText === trackTitle; put(".mini__text", radioText); }
      const play = doc.querySelector('[data-action="play"]');
      if (play) { play.disabled = !!state.buffering || !!state.scanActive || state.canPlay === false || !!state.playing; play.dataset.state = state.buffering ? "loading" : state.playing ? "success" : "default"; }
      const range = doc.querySelector('[data-action="volume"]'); if (range && doc.activeElement !== range) range.value = String(Number(state.volume) || 0);
      const mute = doc.querySelector('[data-action="mute"]'); if (mute) { setText(mute, state.muted ? "◖×" : "◖))"); mute.setAttribute("aria-label", state.muted ? "Unmute" : "Mute"); mute.setAttribute("aria-pressed", String(!!state.muted)); }
      for (const name of ["previous", "next"]) { const el = doc.querySelector(`[data-action="${name}"]`); if (el) el.disabled = state.canNavigate === false || !!state.scanActive; }
      const err = doc.querySelector(".mini__error");
      if (err && state.error) { err.hidden = false; setText(err, state.error); }
      else if (err && !state.error && err.textContent) { err.hidden = true; setText(err, ""); }
      visual?.start?.();
    }
    function close() {
      requested = false;
      const win = target;
      if (childCleanup) childCleanup();
      if (win && !win.closed) win.close();
      target = null;
    }
    function destroy() {
      disposed = true; close();
      if (openerPagehide) { parent.removeEventListener("pagehide", openerPagehide); openerPagehide = null; }
    }
    return { open, close, refresh: () => refresh(true), destroy };
  }
  parent.DABMiniPlayer = { create };
})();
