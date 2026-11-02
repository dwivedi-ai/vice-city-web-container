# How quenq.com runs GTA: Vice City in the browser

Investigated 2026-11-02. Sources: the live site (HTML, JS, response headers), the WASM binary's strings and section headers (inspected in /tmp, then deleted), and public repos and articles listed at the end. No game asset data was downloaded. The only checks against asset URLs were HEAD requests.

## TL;DR

This is not emulation. **reVC** is the community reverse-engineered C++ source of Vice City. **DOS.Zone** (caiiiycuk/js-dos, okhmanyuk-ev, SerGen) compiled it to **WebAssembly with Emscripten**, under the internal name **"vc-sky"** / "revcDOS". It renders through **WebGL2**, plays sound through **Web Audio** (an OpenAL shim), and stores saves in **IndexedDB**.

quenq.com hosts its own copy of the DOS.Zone build. The WASM still has `https://cdn.dos.zone/vcsky/` hard-coded, and a one-line JS shim rewrites it to quenq's own `/vcsky/`. Around that build, quenq added a Vue UI, a save manager, a mod manager and an FPS limiter.

## 1. Page structure

```
quenq.com/apps/vice-city/          ads, SEO text, Disqus
  └─ <iframe src="https://vc.quenq.com">   CSP frame-ancestors limits embedding to quenq/kwenk
        index.html  (Vue 3 + Pinia SPA built with Vite: /assets/index-*.js)
        ├─ /assets/js/GamepadEmulator.js   virtual gamepad for touch
        ├─ /assets/js/idbfs.js             IndexedDB FS helpers
        ├─ /assets/js/game.js              loader: downloads data, builds `Module`
        └─ /assets/js/index.js             loads the Emscripten glue, split into modules:
              runtime.js packages.js loader.js fs.js audio.js graphics.js
              events.js fetch.js asm_consts.js main.js
        └─ /vcsky/vc-sky-en-v6.wasm        the engine (7.6 MB raw, 2.4 MB brotli)
        └─ /vcsky/vc-sky-en-v6.data.00..06 preloaded game data (135,355,111 bytes)
        └─ /vcsky/fetched/...              assets streamed on demand
```

- Opened outside an iframe, vc.quenq.com redirects to quenq.com.
- game.js contains a function disguised as an audio routine, `chunkRe3Audio`. Its strings are XOR-17 encoded. Decoded, it is a **domain lock**: if `location.hostname` is not `localhost` or `*.quenq.com`, it calls `location.replace("https://quenq.com")`.
- The Emscripten glue is not minified, and quenq has edited it by hand. Examples are the `// ---- NEW: SMART CPU-FRIENDLY FPS THROTTLE ----` block in `runtime.js` and the `replaceFetch` hook in `fetch.js`.

## 2. The engine (WASM)

| Fact | Evidence |
|---|---|
| reVC compiled by Emscripten with clang/LLVM 22 | `22.0.0git (llvm-project 60513b8…)` string; `/emsdk/emscripten/...` paths |
| Built by DOS.Zone | Build paths `/home/caiiiycuk/vc/vc-sky/...`; `PACKAGE_NAME = "/home/caiiiycuk/vc/vc-sky/index.data"` |
| RenderWare replaced by **librw** (aap's open RW reimplementation), GL3 backend | `vc-sky/libs/librw/src/gl/gl3raster.cpp`, `rw::Stream...` symbols |
| Wrapped in Okhmanyuk's **"Sky Engine"** framework | `sky::ImguiConsole`, `sky::CVar`, `skygfx::RenderTarget/VertexBuffer/ShaderReflection`, "Sky Engine" string |
| Shaders written as Vulkan-style GLSL 450 and cross-compiled at runtime to WebGL GLSL ES with **glslang + SPIRV-Cross** | `#version 450 core`, `layout(binding = …)`, many SPIRV-Cross/glslang error strings |
| Dear ImGui for the debug console and cvars (plus a cheat menu in the DOS.Zone build) | ImGui strings |
| MP3 decoding inside WASM with the **mpg123** Emscripten port | `/emsdk/emscripten/cache/ports/mpg123/mpg123-1.26.2/...` |
| **Single-threaded**: memory is not shared, there are no pthreads, no SharedArrayBuffer | Memory section flags = 1 (not shared). So COOP/COEP headers aren't needed, and it works inside a cross-origin iframe |
| Memory: 128 MB at start, can grow to 2 GB | Memory section: min 2048 pages, max 32768 |
| C++ exceptions through Emscripten's JS-based EH | `__cxa_find_matching_catch_*` imports |
| 615 JS imports and 16 minified exports (`_main`, `malloc`, …) | Import/export sections |

DOS.Zone also changed the engine to be **asynchronous**. In their words: "revcDOS is a completely asynchronous game. From time to time, it will request additional files as they are needed." A browser can't block on file I/O, so missing files are requested with `emscripten_fetch` while the game keeps running. The engine flips `document.body.dataset.stateDownload` so the UI can show a "downloading" indicator.

## 3. How the game data gets there

**a) Preload: 135 MB, 1,943 files** (manifest in `modules/packages.js`)
- Packed with Emscripten's `file_packager`, then split into **7 chunks of 20 MB** (`.data.00`–`.06`).
- game.js downloads all 7 **in parallel** with `fetch()` streaming readers, shows a progress bar, and stores each chunk in the **Cache Storage API** (`caches.open(hostname + '-chunks-v2')`). Later visits skip the network.
- The chunks are joined into one `Uint8Array` and passed in through `Module.getPreloadedPackage`. `loader.js` then creates each file in **MEMFS** as a zero-copy `subarray` of that buffer, under `/vc-assets/local/...`.
- Breakdown: `models/gta3.img/*` 68.5 MB in 1,722 files, `audio/flash.adf` 25.5 MB (the only radio station), `data/maps` 9 MB, cutscene anims 5.4 MB, plus TXDs, text, `main.scm` and the rest.
- **gta3.img is unpacked into separate files** (`/models/gta3.img/<name>.dff`) instead of one 2 GB-style archive. The modified streamer reads a directory. That is also why the mod manager can replace a single file and patch its sector size in `gta3.dir`.

**b) On-demand streaming** (`/vcsky/fetched/...`)
- Mission and cutscene audio and cutscene animations are fetched only when needed. HEAD checks:
  - `fetched/audio/city.mp3`: 200, 3.9 MB, audio/mpeg
  - `fetched/audio/ass_1.mp3`: 200, 133 KB
  - `fetched/anim/cuts.img/ass_1.ifp`: 200, 266 KB
- The WASM contains about 2,450 `AUDIO\*.WAV` / `*.MP3` names. All audio was transcoded to MP3 offline.
- DOS.Zone's data-compile Docker image does this conversion: ADF → MP3 (Wine + `adf2mp3.exe` + ffmpeg), WAV/RAW → MP3, `.img` extracted using its `.dir`.

**c) Things quenq dropped or stubbed**
- Only Flash FM is shipped. Before `main`, game.js writes a **5-second silent MP3** for Emotion, Espantoso, Fever, K-Chat, VCPR, V-Rock, Wave and Wildstyle so the engine doesn't fail on the missing files.
- `NoMovies=0` is set, but no movie files are included.

**d) Caching and compression**
- Cloudflare serves everything with `max-age=31536000` (1 year).
- The WASM is brotli-compressed on the wire (7.6 → 2.4 MB).
- The data chunks are **sent uncompressed** (20,971,520 bytes even with `Accept-Encoding: br`). Compressing them is an easy win quenq hasn't taken (see §7).

## 4. Rendering

- One `<canvas id="canvas">`. Emscripten's GL layer creates a **WebGL2** context (WebGL1 fallback) with `antialias:false, alpha:false`. Many extensions are enabled when present: S3TC/DXT (the original textures are DXT1–5), anisotropic filtering, `KHR_parallel_shader_compile`, multi_draw, and others.
- librw's GL3 backend plus skygfx render the RW scene, with an option for a newer pipeline (`[Rendering] NewRenderer=1`, `BackfaceCulling=1`).
- Settings come from a `revc.ini` generated in game.js and stored in localStorage (`vcsky.revc.ini`). Defaults: 800×600, `DrawDistance=1.8`, Ped/Car density 1.2, VSync on, MSAA 0, PS2 alpha test, PS2 colour filter (`ColourFilter=2`), motion blur off, and the reVC "Neo" pipelines (rim light, lightmaps, road gloss) off. Widescreen fixes `ProperScaling/FixRadar/FixSprites` are on.
- If the WebGL context is lost, the page shows an alert asking you to reload. There is no recovery.

## 5. Main loop, audio, input, saves

- **Main loop:** `emscripten_set_main_loop`, driven by `requestAnimationFrame`. quenq's patch to `MainLoop.runner` adds an FPS cap that skips rAF ticks until `1000/fps` ms have passed (`Module._setFPSLimit`, `?max_fps=`). The default is 0 (uncapped). The site's own FAQ says uncapped frame rates break the original physics and some missions, and recommends capping at 30.
- **Audio:** reVC's OpenAL backend runs on Emscripten's **OpenAL-over-Web-Audio** shim (`audio.js`: `alGenSources`, panners and the rest), plus SDL2 audio. MP3 is decoded by mpg123 in WASM. The AudioContext is resumed on user input to satisfy autoplay rules.
- **Input:** Emscripten HTML5 callbacks handle keyboard, mouse, wheel, pointer lock, touch, gamepad, focus and visibility. Key bindings live in `revc.ini [Bindings]`. The real **Gamepad API** handles Xbox/PS pads.
  - On touch devices, `GamepadEmulator.js` creates a **fake gamepad**: two virtual joysticks plus about 15 HTML buttons mapped to pad button indices.
  - The engine pushes game state (in car, on foot with gun, menu, cutscene, phone ringing, sniper scope, and so on) to `<body data-state-*>` through `EM_ASM` calls (`asm_consts.js`). CSS uses these attributes to show only the touch buttons that make sense at that moment.
  - A hidden `<input>` turns mobile keyboard text into synthetic key events for cheat entry.
- **Saves:** `/vc-assets/local/userfiles` is mounted as **IDBFS**. The engine calls `FS.syncfs` through EM_ASM after saving, so `GTAVCsf1..8.b` persist in IndexedDB. The Vue save manager reads and writes that same IndexedDB store directly for upload and download, and it removes invalid saves over 512 KB.
  - DOS.Zone's original build used js-dos **cloud saves** instead. quenq replaced them with local saves.
- **Mods:** `.dff`/`.txd`/skin files kept in an IndexedDB store (`vcsky_mods_db`) are written into MEMFS in `onRuntimeInitialized`. For each one, the matching 32-byte `gta3.dir` entry gets its size in 2048-byte sectors updated.

## 6. Where it comes from, and legal status

- Dec 2025: DOS.Zone launched "reVCDOS". It was free as a demo; the full game needed you to supply your own files, checked by SHA-256. After DMCA pressure (Take-Two/EBRAND), DOS.Zone pulled the hosted version and **published the binaries**.
- Community repos (Lolendor/reVCDOS, yukonga/revcdos, DevHarsh001/revcdos) then made a deobfuscated, self-hostable version. It is a Python/PHP proxy whose defaults are `--vcsky_url https://cdn.dos.zone/vcsky/` and `--vcbr_url https://br.cdn.dos.zone/vcsky/`, which is the same layout quenq uses. `cdn.dos.zone/vcsky/` now returns 403.
- quenq.com hosts the full commercial game data (Rockstar's copyrighted assets) on its own Cloudflare origin and shows no authorization from the rights holders. **This is legally exposed.** Learning from the technique is fine; copying their asset hosting is not.

## 7. Takeaways for an "optimized" build

1. **Compress the data chunks** (brotli or zstd, or ship `.br` files with `Content-Encoding`). They are sent raw today, and game data usually shrinks a lot.
2. **Stream more instead of preloading.** The 68 MB of `gta3.img` entries could be fetched per model through the same async path already used for audio, with a small starter set preloaded. DOS.Zone's own notes say about 50 MB is enough to boot.
3. **Use OPFS or Cache Storage per file** instead of 7 large blobs, so one changed asset doesn't invalidate a 20 MB chunk.
4. **Cap the frame rate at 30 for the simulation and render at display rate**, or decouple the two in the engine, instead of offering a choice between "uncapped" (breaks physics) and "30".
5. **Possible further steps:** WASM SIMD, pthreads/SharedArrayBuffer (needs COOP/COEP, which complicates iframe embedding), cached compiled shaders, and recovery from lost WebGL contexts.

## Sources
- Live: https://quenq.com/apps/vice-city/ and https://vc.quenq.com/ (copies of the HTML/JS in `research/raw/`)
- https://github.com/DevHarsh001/revcdos — DOS.Zone's release notes (async engine, `getAsyncUrl`, data-compile pipeline)
- https://github.com/Lolendor/reVCDOS and https://github.com/yukonga/revcdos — deobfuscated self-hosting server
- https://korben.info/en/revcdos-vice-city-in-a-browser-tab.html
- https://wccftech.com/playing-gta-vice-city-in-a-web-browser-is-now-possible-thanks-to-dos-zone/amp/
- https://www.notebookcheck.net/Grand-Theft-Auto-Vice-City-is-now-playable-everywhere-through-a-browser-port.1189117.0.html
