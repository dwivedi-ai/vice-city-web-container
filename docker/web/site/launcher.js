// Host page for DOS.Zone's revcDOS build. It plays the role of their
// host.html: the engine (in the iframe) asks the top window for its boot
// files ("module.initfs" / "module.initfile") and for later assets
// ("module.getasyncurl"). Here the files come from this server instead of
// a folder picker.
//
// What makes it fast:
//  - the boot files arrive as small, verified precompressed chunks fetched in
//    parallel. Downloading starts while the start screen is still showing,
//    and the parts are kept in Cache Storage for the next visit;
//  - related on-demand assets share verified packs and fill the native
//    filesystem ahead of demand; temporary delivery URLs are released;
//  - optional ?fps=N caps the frame rate with no busy-waiting;
//  - automatic texture quality adapts to measured download speed.

import { download, loadChunks, openCache } from "./download.mjs";
import { createAssetStore, installBlobDelivery } from "./stream-assets.mjs";
import { createAudioStore } from "./audio-assets.mjs";

const params = new URLSearchParams(location.search);
const fpsCap = Math.max(0, parseInt(params.get("fps") || "0", 10) || 0);

const iframe = document.getElementById("game");
const bar = document.getElementById("bar");
const errorEl = document.getElementById("error");
let dataReady = false;
let progressText = "Loading game…";

const SOUND_CACHE = "vc-assets/local/audio/sound.cache";

function setProgress(fraction, text) {
  bar.style.width = `${Math.round(fraction * 100)}%`;
  if (text !== undefined) progressText = text;
  iframe.contentWindow?.postMessage({ event: "launcher.progress", ready: dataReady, text: progressText }, location.origin);
}

async function loadManifest() {
  const index = JSON.parse(new TextDecoder().decode(await download("data/stream/index.json")));
  let quality = params.get("quality");
  if (!["low", "full"].includes(quality)) {
    let started = 0, wireBytes = 0;
    try {
      const cache = await openCache("vc-preload");
      await download(new URL(`data/${index.probe.url}`, location.href).href, index.probe, {
        cache, timeoutMs: 8000, attempts: 1,
        onResponse: response => {
          started = performance.now();
          wireBytes = Number(response.headers.get("Content-Length"));
        },
      });
      const speed = started ? wireBytes / Math.max(.001, (performance.now() - started) / 1000) : 0;
      let previous = "low";
      try { previous = localStorage.getItem("vc.auto-quality") || "low"; } catch {}
      if (!["low", "full"].includes(previous)) previous = "low";
      quality = navigator.connection?.saveData ? "low" : started ? (speed >= 750000 ? "full" : "low") : previous;
    } catch { quality = "low"; }
    try { localStorage.setItem("vc.auto-quality", quality); } catch {}
  }

  const bytes = await download(new URL(`data/${index.profiles[quality]}`, location.href).href);
  const manifest = JSON.parse(new TextDecoder().decode(bytes));
  document.documentElement.dataset.quality = quality;
  return manifest;
}

async function loadPreload(manifest, signal) {
  let lastPercent = -1;
  const all = await loadChunks(manifest.preload, new URL("data/", location.href), {
    signal,
    onProgress: (loaded, size) => {
      const percent = Math.min(100, Math.floor(loaded / size * 100));
      if (percent !== lastPercent) {
        lastPercent = percent;
        setProgress(loaded / size, `Loading game data… ${percent}%`);
      }
    },
    onRetry: () => setProgress(Math.max(0, lastPercent) / 100, "Connection interrupted. Retrying…"),
  });
  setProgress(1, "Preparing game…");
  return all;
}

function showError(error) {
  dataReady = false;
  errorEl.replaceChildren();
  const message = document.createElement("p");
  message.textContent = `Unable to load the game: ${error.message || "connection interrupted"}.`;
  const retry = document.createElement("button");
  retry.type = "button";
  retry.textContent = "Retry";
  retry.onclick = () => location.reload();
  const panel = document.createElement("div");
  panel.append(message, retry);
  errorEl.append(panel);
  errorEl.style.display = "grid";
}

function assetUrl(manifest, file) {
  return new URL(`data/${file}?v=${manifest.version}`, location.href).href;
}

function normalize(file) {
  return file.replaceAll("\\", "/").replace(/\/+/g, "/").replace(/^\//, "").toLowerCase();
}

function installFrameHooks(win, manifest, available, store, audio) {
  if (win.__launcherHooksInstalled) return;
  win.__launcherHooksInstalled = true;
  // Keyboard Lock is restricted to the top-level browsing context. Failure is
  // optional (for example before fullscreen), so never reject engine startup.
  if (win.navigator.keyboard?.lock) {
    win.navigator.keyboard.lock = async (keys) => {
      try { await navigator.keyboard?.lock(keys); } catch {}
    };
  }
  // game.js does `window.Module = Module` when the player clicks play, and
  // the engine reaches assets through that object. Hand it real URLs for
  // on-demand assets. Install as early as possible, and adopt a Module that
  // is already there.
  const packedUrl = installBlobDelivery(win, {
    stats: store.stats, read: file => audio.has(file) ? audio.read(file) : store.read(file),
  });
  const hook = (value) => {
    if (value && typeof value === "object" && "getAsyncUrl" in value && !value.__fastAsync) {
      value.__fastAsync = true;
      const initialize = value.initFS;
      value.initFS = async (...args) => {
        const result = await initialize.apply(value, args);
        // The upstream mainCalled creates /vc-assets with exclusive mkdir.
        // Wait for its core setup before inserting speculative scene files.
        store.attachFS(value.FS || win.FS);
        return result;
      };
      value.getAsyncUrl = (file) => {
        const f = normalize(file);
        if (!available.has(f)) return Promise.reject(new Error(`File not found: ${f}`));
        if (store.has(f) || audio.has(f)) return packedUrl(f).catch(error => {
          console.warn(`Cached download unavailable; falling back to original asset: ${f}`, error);
          return assetUrl(manifest, f);
        });
        return Promise.resolve(assetUrl(manifest, f));
      };
    }
    return value;
  };
  let mod = hook(win.Module);
  Object.defineProperty(win, "Module", {
    configurable: true,
    get: () => mod,
    set: (value) => { mod = hook(value); },
  });

  // Referenced by game.js' hotelMission hook; we only run with the player's own game files.
  win.haveOriginalGame = true;

  if (fpsCap > 0) {
    const raf = win.requestAnimationFrame.bind(win);
    const interval = 1000 / fpsCap;
    let last = 0;
    win.requestAnimationFrame = (cb) =>
      raf(function tick(t) {
        if (last && t - last < interval - 1) return raf(tick);
        last = last && t - last < interval * 2 ? last + interval : t;
        cb(t);
      });
  }
}

async function main() {
  const manifest = await loadManifest();
  const available = new Set(manifest.files);
  const store = createAssetStore(manifest, new URL("data/", location.href));
  const audio = createAudioStore(
    manifest.files.filter(file => /\/audio\/.*\.(adf|mp3|wav)$/.test(file) && !store.has(file)),
    file => assetUrl(manifest, file),
  );
  window.addEventListener("pagehide", () => { store.close(); audio.close(); }, { once: true });
  window.__audioStats = audio.stats;
  window.__assetStats = store.stats;
  const files = manifest.preload.files.filter(([path]) => path !== SOUND_CACHE);

  // Read separately so older boot packs can use a newly generated audio index.
  // Without durations, the engine divides by zero while initializing streams
  // that have intentionally not been downloaded yet.
  const startup = new AbortController();
  const soundCachePromise = download(assetUrl(manifest, SOUND_CACHE), manifest.soundCache, { signal: startup.signal });

  let preloadPromise = Promise.all([loadPreload(manifest, startup.signal), soundCachePromise]);
  preloadPromise.then(() => {
    dataReady = true;
    setProgress(1, "");
    bar.classList.add("done");
    // Use the time spent at the Start button and initializing WebAssembly.
    // The finite scene queue yields to demand and remains in the pack cache
    // until the engine's filesystem is available.
    store.prefetch();
  }).catch((error) => {
    startup.abort(error);
    showError(error);
  });

  iframe.addEventListener("load", () => {
    installFrameHooks(iframe.contentWindow, manifest, available, store, audio);
    iframe.contentWindow.postMessage({ event: "launcher.progress", ready: dataReady, text: progressText }, location.origin);
  });
  iframe.src = `engine/index.html${location.search}`;
  // Install the hooks the moment the engine page's document exists (before its
  // scripts can run user-triggered code), not at the late iframe "load" event.
  const engineUrl = new URL(iframe.src, location.href).pathname;
  (function waitForEngineDocument() {
    const win = iframe.contentWindow;
    let ready = false;
    try { ready = win.location.pathname === engineUrl && win.document.readyState !== "uninitialized"; } catch {}
    if (ready) installFrameHooks(win, manifest, available, store, audio);
    else setTimeout(waitForEngineDocument, 4);
  })();

  let preload = null;
  let soundCache = null;
  let next = 0;
  window.addEventListener("message", async (event) => {
    if (event.source !== iframe.contentWindow || event.origin !== location.origin) return;
    const data = event.data || {};
    const reply = (msg, transfer) => event.source.postMessage(msg, location.origin, transfer);

    switch (data.event) {
      case "game.started":
        store.prefetch();
        break;
      case "module.initfs":
        [preload, soundCache] = await preloadPromise;
        next = 0;
        reply({ event: ">module.initfs", files: files.length + 1 });
        break;
      case "module.initfile": {
        if (next === files.length) {
          next++;
          reply({ event: ">module.initfile", path: SOUND_CACHE, data: soundCache }, [soundCache.buffer]);
          preloadPromise = null;
          preload = null;
          soundCache = null;
          bar.classList.add("done");
          break;
        }
        const entry = files[next++];
        if (!entry) return console.error("engine asked for more boot files than exist");
        const [path, offset, size] = entry;
        const bytes = preload.slice(offset, offset + size);
        reply({ event: ">module.initfile", path, data: bytes }, [bytes.buffer]);
        break;
      }
      case "module.getasyncurl": {
        // Fallback path, used only if the Module hook above didn't take.
        const f = normalize(data.file || "");
        if (!available.has(f)) return reply({ event: ">module.getasyncurl", file: data.file });
        const bytes = store.has(f) ? await store.read(f) : audio.has(f) ? await audio.read(f) : await download(assetUrl(manifest, f));
        const buf = bytes.buffer;
        reply({ event: ">module.getasyncurl", file: data.file, data: new Uint8Array(buf) }, [buf]);
        break;
      }
      case "request-fullscreen":
        if (!document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
        break;
    }
  });
}

main().catch(showError);
