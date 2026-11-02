// Host page for DOS.Zone's revcDOS build. It plays the role of their
// host.html: the engine (in the iframe) asks the top window for its boot
// files ("module.initfs" / "module.initfile") and for later assets
// ("module.getasyncurl"). Here the files come from this server instead of
// a folder picker.
//
// What makes it fast:
//  - the boot files arrive as a few large precompressed parts fetched in
//    parallel. Downloading starts while the start screen is still showing,
//    and the parts are kept in Cache Storage for the next visit;
//  - on-demand assets are served by URL (versioned, cached as immutable)
//    instead of as blob: URLs, which game.js never revokes;
//  - optional ?fps=N caps the frame rate with no busy-waiting;
//  - optional ?prefetch=1 warms the HTTP cache with the remaining models
//    and animations once the game is running.

const params = new URLSearchParams(location.search);
const fpsCap = Math.max(0, parseInt(params.get("fps") || "0", 10) || 0);
const prefetch = params.get("prefetch") === "1";

const iframe = document.getElementById("game");
const bar = document.getElementById("bar");
const statusEl = document.getElementById("status");
const noteEl = document.getElementById("note");
const errorEl = document.getElementById("error");

const PRELOAD_CACHE = "vc-preload";

function setProgress(fraction, text) {
  bar.style.width = `${Math.round(fraction * 100)}%`;
  if (text) statusEl.textContent = text;
}

function fail(message) {
  errorEl.textContent = message;
  errorEl.style.display = "grid";
  throw new Error(message);
}

async function loadManifest() {
  const res = await fetch("data/bundle/manifest.json", { cache: "no-cache" });
  if (!res.ok) fail("Game data not found. Run the prepare step first (see README).");
  return res.json();
}

async function fetchPart(cache, part, onBytes) {
  const url = new URL(part.url, new URL("data/", location.href)).href;
  let res = cache && (await cache.match(url));
  if (!res) {
    res = await fetch(url);
    if (!res.ok) throw new Error(`${res.status} ${url}`);
  }
  // Content-Length is the compressed size and the stream gives decoded bytes,
  // so progress is counted in decoded bytes against part.size.
  const reader = res.clone().body.getReader();
  const out = new Uint8Array(part.size);
  let at = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    out.set(value, at);
    at += value.length;
    onBytes(value.length);
  }
  if (at !== part.size) throw new Error(`short read on ${url}: ${at}/${part.size}`);
  if (cache && !(await cache.match(url))) await cache.put(url, new Response(out));
  return out;
}

async function loadPreload(manifest) {
  const { size, parts } = manifest.preload;
  let cache = null;
  try {
    cache = await caches.open(PRELOAD_CACHE);
    for (const req of await cache.keys()) {
      if (!req.url.includes(manifest.version)) await cache.delete(req);
    }
  } catch {
    // Cache Storage needs a secure context (https or localhost); the HTTP cache still applies.
  }
  let loaded = 0;
  const onBytes = (n) => {
    loaded += n;
    setProgress(loaded / size, `Loading game data… ${Math.floor((loaded / size) * 100)}%`);
  };
  const buffers = await Promise.all(parts.map((p) => fetchPart(cache, p, onBytes)));
  const all = new Uint8Array(size);
  let at = 0;
  for (const b of buffers) {
    all.set(b, at);
    at += b.length;
  }
  setProgress(1, "Game data ready - click to play");
  return all;
}

function assetUrl(manifest, file) {
  return new URL(`data/${file}?v=${manifest.version}`, location.href).href;
}

function normalize(file) {
  return file.replaceAll("\\", "/").replace(/\/+/g, "/").replace(/^\//, "").toLowerCase();
}

function installFrameHooks(win, manifest, available) {
  // game.js does `window.Module = Module` when the player clicks play, and
  // the engine reaches assets through that object. Hand it real URLs for
  // on-demand assets. Install as early as possible, and adopt a Module that
  // is already there.
  const hook = (value) => {
    if (value && typeof value === "object" && "getAsyncUrl" in value && !value.__fastAsync) {
      value.__fastAsync = true;
      value.getAsyncUrl = (file) => {
        const f = normalize(file);
        return available.has(f) ? Promise.resolve(assetUrl(manifest, f)) : Promise.reject(new Error(`File not found: ${f}`));
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

function startPrefetch(manifest, available) {
  const queue = [...available].filter((f) => !/\.(mp3|wav)$/.test(f) && !preloadedSet.has(f));
  let i = 0;
  const step = async (deadline) => {
    while (i < queue.length && (!deadline || deadline.timeRemaining() > 5)) {
      const url = assetUrl(manifest, queue[i++]);
      try { await fetch(url, { priority: "low" }); } catch {}
    }
    if (i < queue.length) requestIdleCallback(step, { timeout: 2000 });
  };
  requestIdleCallback(step, { timeout: 2000 });
}

let preloadedSet = new Set();

async function main() {
  const manifest = await loadManifest();
  const available = new Set(manifest.files);
  const files = manifest.preload.files;
  preloadedSet = new Set(files.map((f) => f[0]));

  const preloadPromise = loadPreload(manifest).catch((e) => fail(`Failed to download game data: ${e.message}`));

  iframe.src = `engine/index.html${location.search}`;
  // Install the hooks the moment the engine page's document exists (before its
  // scripts can run user-triggered code), not at the late iframe "load" event.
  const engineUrl = new URL(iframe.src, location.href).pathname;
  (function waitForEngineDocument() {
    const win = iframe.contentWindow;
    let ready = false;
    try { ready = win.location.pathname === engineUrl && win.document.readyState !== "uninitialized"; } catch {}
    if (ready) installFrameHooks(win, manifest, available);
    else setTimeout(waitForEngineDocument, 4);
  })();

  let preload = null;
  let next = 0;
  window.addEventListener("message", async (event) => {
    if (event.source !== iframe.contentWindow) return;
    const data = event.data || {};
    const reply = (msg, transfer) => event.source.postMessage(msg, "*", transfer);

    switch (data.event) {
      case "module.initfs":
        statusEl.textContent = "Starting engine…";
        preload = await preloadPromise;
        next = 0;
        reply({ event: ">module.initfs", files: files.length });
        break;
      case "module.initfile": {
        const entry = files[next++];
        if (!entry) return console.error("engine asked for more boot files than exist");
        const [path, offset, size] = entry;
        const bytes = preload.slice(offset, offset + size);
        reply({ event: ">module.initfile", path, data: bytes }, [bytes.buffer]);
        if (next === files.length) {
          preload = null; // let the big buffer go
          noteEl.classList.add("done");
          bar.classList.add("done");
          if (prefetch) startPrefetch(manifest, available);
        }
        break;
      }
      case "module.getasyncurl": {
        // Fallback path, used only if the Module hook above didn't take.
        const f = normalize(data.file || "");
        if (!available.has(f)) return reply({ event: ">module.getasyncurl", file: data.file });
        const buf = await (await fetch(assetUrl(manifest, f))).arrayBuffer();
        reply({ event: ">module.getasyncurl", file: data.file, data: new Uint8Array(buf) }, [buf]);
        break;
      }
      case "request-fullscreen":
        if (!document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
        break;
    }
  });
}

main();
