# Launchpad loading and asset-streaming investigation

Date: 2026-11-03, Asia/Kolkata. Initial deployment captures are from 2026-11-02 UTC; the subsequent implementation and benchmarks are from 2026-11-03.

## Objective and current state

Investigate very slow loading on Launchpad, followed by loading screens and missing textures during play. Local play is fast. Preserve the existing product requirements: one self-contained Docker image, minimal **Start game** screen, no cloud-save integration, and persistent local browser saves.

- Deployment: <https://gta-xo-su1mcue.apps.hello-xo.nl/>
- Private source repository: <https://github.com/dwivedi-ai/revcdos-selfhost>
- Source baseline: `50ded74a4990104100a08974c80a83caf15be150`.
- Published image: `registry.xo.builders/gta-xo-su1mcue/app:latest`, built for `linux/amd64`.
- Last published image-index digest: `sha256:62c0b935681f051c2b980092e708446697588ce47c3b1883df9127ce2ab2a939`.
- Live boot manifest version: `4525c56b32bd32cc`, matching the local baseline. The live container's image digest was not independently available through Launchpad.

**The performance results below are from local verification, not a post-release production measurement.** The sections below record the original investigation, the first implemented optimization, and the newer adaptive streaming implementation. The final section is the current implementation status; earlier rejected prototypes are historical context. Public-deployment performance and the original missing-texture report still need a post-release check.

## Findings

### 1. Startup downloads too much before enabling the button

The launcher waits for every preload part and the audio-duration index before enabling Start game. The current manifest contains **1,917 preloaded files totaling 126,914,308 decoded bytes**. Browser measurements recorded approximately **74.16 MB transferred** for the parent page's resources, mostly startup data. This is an upfront network download, not an image pull or server-side game launch.

Largest contributors:

| Boot content | Decoded bytes |
|---|---:|
| `models/gta3.img/*`, including its preloaded collisions | 68,460,544 |
| `audio/flash.adf` — a full radio-station audio file | 28,703,364 |
| `data/maps/*` | 9,092,950 |
| `anim/cuts.img/*` | 5,398,528 |
| `anim/ped.ifp` | 2,201,152 |

The radio track alone is about 23% of decoded boot bytes and is already compressed audio, so transport compression saves little on it. Removing it from mandatory startup is a concrete opportunity, subject to testing radio playback through the engine's existing on-demand path.

### 2. The deployed transfer speed reproduces the reported wait

Measured against the live URL from this development machine:

| Request | Result |
|---|---|
| Root HTML | HTTP/2 200; TTFB 0.828 s |
| Compressed manifest | HTTP/2 200; 57,397 transferred bytes; 1.405 s total |
| First boot part, explicitly requesting Brotli | HTTP/2 200; 7,341,970 bytes in **29.130 s**, approximately **252,041 bytes/s** |
| Texture `wshxreflod.txd`, fresh connection | 200; 20,480 bytes; 1.191 s total |
| Model `lodxrefhirise1.dff`, fresh connection | 200; 6,144 bytes; 1.166 s total |

At approximately 0.25 MB/s, a 74 MB initial transfer would take roughly **five minutes**. This fits the user's observation of a few seconds per percentage point. This is an observed effective transfer rate, **not proof of a configured Launchpad bandwidth cap**. Hosting egress, proxy behavior, route/congestion, and the client's connection remain possible contributors.

A cold Chrome visit to the real deployment was not ready after **240.128 seconds**. At **448.045 seconds** after navigation it showed **96%** and a disabled Start game button. A final inspection at approximately **559 seconds** found the outer error overlay: **`Failed to load the game: network error`**. Thus the later 96% observation was not proof that a healthy download was still progressing; it was a failed load.

Final resource timing entries identified incomplete responses even though their recorded HTTP status was 200:

| Boot part | Expected compressed bytes (local matching sidecar) | Browser encoded bytes | Expected decoded bytes | Browser decoded bytes | Duration |
|---|---:|---:|---:|---:|---:|
| `…-3.bin`, Zstandard | 8,436,893 | 8,302,400 | 16,777,216 | 16,384,000 | 248.285 s |
| `…-4.bin`, Zstandard | 11,688,304 | 7,778,080 | 16,777,216 | 12,862,865 | 239.886 s |

Other parts completed, including the uncompressed 16 MiB part 5, which took 288.015 s. The two decoded shortfalls account for approximately 3.4% of boot bytes, consistent with the UI stopping at 96%. `Promise.all` rejection does not cancel the other fetches, so those downloads can continue updating progress after one has failed.

**Interpretation and limits:** the browser run demonstrates incomplete delivery to the loader, not an HTTP 404. It does not establish which layer interrupted the responses. Exact `Network.loadingFailed` details were not captured across every CDP connection boundary. The benchmark changed/detached CDP sessions during observation; repeat with passive, continuous network recording and no network-emulation changes before assigning the interruption to a Launchpad timeout. Do not infer a fixed 240-second proxy limit just from the clustered durations.

An independent, isolated retry of part 4 subsequently succeeded: HTTP/2 200, **11,688,304 compressed bytes in 48.337 seconds** (241,807 bytes/s). Zstandard decoding produced all **16,777,216 bytes**, identical byte for byte to the local baseline. Decoded SHA-256: `214052bc91a7d0177463dad62aad9c34b44f237895178b3aa32d68e52fca5557`. This verifies that this stored bundle can be delivered intact; it does not rule out interruptions under concurrent loading. The retry downloaded the compressed body directly and decoded it with `zstd`, because the installed curl cannot itself decode Zstandard.

The initial observation window recorded no HTTP error statuses or JavaScript exceptions. That did not guarantee body completeness. Completed resource timing entries alone also undercount in-progress transfers. The single-file rate should not be treated as a guaranteed sustained rate for the whole load.

Fresh-connection timings include TLS setup. A subsequent same-connection test measured approximately **270–276 ms TTFB** for small requests with no new connection. Another 71 KB model took 5.225 s during the ongoing browser download; that particular measurement was contending with startup traffic and must not be presented as an isolated per-file rate.

### 3. Boot compression works; streamed-model compression is missing

The live boot part responds with `Content-Encoding: zstd` when offered all common encodings, or `br` when requested explicitly. It also sends `Cache-Control: public, max-age=31536000, immutable` and `Vary: Accept-Encoding`.

However, the sampled individual texture/model assets were served as `application/octet-stream` **without Content-Encoding**, even with `Accept-Encoding: br, zstd, gzip`. The same behavior occurs locally. The final build uses `--compression boot`, so individual model/texture sidecars are absent. The generic `encode` directive does not compress these sampled responses under the current configuration.

Local compression of actual deployed asset bytes demonstrates useful savings:

| Asset | Current bytes | Brotli quality 6 | Reduction |
|---|---:|---:|---:|
| `wshxreflod.txd` | 20,480 | 14,034 | 31.5% |
| `cop.dff` | 71,680 | 30,787 | 57.0% |
| `washmallnew.txd` | 784,384 | 568,897 | 27.5% |

Precompress appropriate streamed assets **at build time**, including `.dff`, `.txd`, and relevant animation/data files. Avoid repeatedly recompressing MP3 payloads stored as `.mp3`, `.wav`, or `.adf`. This preserves runtime CPU for serving requests on the one-CPU deployment.

### 4. Gameplay stalls are consistent with on-demand streaming

The engine requests additional files through `Module.getAsyncUrl`. The launcher currently returns one asset URL per request. Engine traces show sequences of `Trying to fetch ...`, completion, then the next model request. A burst of sequential dependencies accumulates network round trips even when HTTP/2 is available.

At approximately 270 ms warm-request latency, 100 sequential dependencies can add roughly 27 seconds before accounting for payload transfer. Uncompressed assets add bandwidth cost. This explains a plausible mechanism for loading screens or late textures in new areas.

**Limits of the finding:** sampled live model/texture files returned 200. The browser subsequently encountered incomplete startup-bundle responses, making delivery failures another concrete concern, but no specific failed texture URL from the user's affected area has been captured. We have not established whether every missing texture is merely late; actual 404s, timeouts, rejected asset lookups, rendering problems, or data mismatches still need to be checked in an affected gameplay trace. Do not describe the replacement game files as corrupt based on these symptoms alone.

## What the provided Caddy logs mean

- `GOMAXPROCS=1` reports a one-CPU quota. It does not show CPU utilization or prove saturation.
- `GOMEMLIMIT=3865470566` is about 3.6 GiB of Go memory limit. It is not evidence of an out-of-memory event.
- The HTTP/2 and HTTP/3 warnings describe Caddy's internal cleartext listener on `:8080`. The public deployment was directly verified to negotiate **HTTP/2**. Enabling TLS inside the container is not an evidenced fix for this issue.
- `admin endpoint disabled` is intentional in the Caddyfile.
- These are normal startup messages, without per-request duration, status, or byte counts. They cannot establish the cause of the missing textures or the location of the throughput bottleneck.

## Experiment: a smaller boot is faster, but naive deferral is insufficient

An isolated local variant retained synchronous core files/collisions and removed these from mandatory preload:

- Audio payloads ending in `.adf`, `.mp3`, or `.wav`.
- `models/gta3.img/*` except `.col`.
- `anim/cuts.img/*`.

The resulting boot contains **218 files, 31,020,179 decoded bytes, and 10,204,802 Brotli-compressed bundle bytes**. All game files remain available at their normal on-demand URLs. The production image was not changed.

Cold browser comparison, with Cache Storage cleared and HTTP cache disabled, under Chrome CDP throttling of **750,000 download bytes/s (6 Mbps) and 80 ms latency**:

| Variant | Time until Start game enabled | Recorded parent-page transfer |
|---|---:|---:|
| Current build | **99.741 s** | **74,164,760 bytes** |
| Experimental smaller boot | **14.210 s** | **10,287,823 bytes** |

The experiment reached the main menu. **New Game then produced a model-loading screen with sequential model requests.** One captured request set already included 58 model URLs. The experiment therefore moves part of the delay into gameplay. It is not a demonstrated 7× improvement to time-to-playable-world, and it must not be shipped as the complete fix.

The candidate server was limited to one CPU and 4 GiB RAM. The baseline local server was not CPU-limited. Both served precompressed boot data. These tests establish the payload/latency opportunity, not exact Launchpad performance or mobile rendering performance.

## Recommended implementation sequence

### First: reduce unnecessary bytes without worsening streaming

1. Keep the current working model preload while testing removal of the full Flash FM track from mandatory startup. Verify first vehicle entry, station selection, radio playback, and continued movement while audio arrives.
2. Generate precompressed sidecars for streamed model/texture/animation assets during the image build. Validate `Content-Encoding` through the public Launchpad URL, not only localhost.
3. Prefer the smallest appropriate precompressed format. `precompressed br zstd gzip` can help where Brotli is smaller, but changing preference alone will not solve the much larger bandwidth and round-trip costs.
4. Measure the same file from another client/network or hosting region and inspect Launchpad egress/proxy limits and live CPU throttling. Compare direct-origin delivery if the platform provides an authorized origin endpoint.
5. Evaluate an asset CDN/edge cache in front of the same immutable URLs if origin delivery remains slow. Preserve `Content-Encoding`, `Vary`, cache keys, and versioned URLs. The current headers support browser caching; the observed headers alone do not establish whether an edge cache exists or is working.
6. Investigate body truncation with continuous passive browser recording, origin/proxy request logs, exact byte counts, and bounded standalone downloads. Consider smaller independently cached/retriable chunks so a slow 16 MiB request cannot invalidate the whole startup. Do not add endless retries or cache partial responses.

### Then: redesign streaming around dependency packs

Use a small boot pack **together with** model/texture packs and background loading, rather than thousands of individual late requests.

- Build deterministic, content-addressed packs with a file-to-pack index.
- Group the known first-scene dependencies together; use IDE/IPL region/model relationships where practical for later areas. Blind alphabetical grouping can overfetch unrelated assets.
- Fetch a bounded number of packs in parallel and deduplicate concurrent requests for the same pack.
- Warm upcoming dependencies while the engine initializes, at the menu, or during cutscenes. Demand requests must take priority over speculative prefetch.
- Supply decoded pack members through a tested filesystem/asset-resolver integration. Preserve the synchronous collision/configuration files required by this engine.
- Budget memory and release temporary buffers/object URLs if that mechanism is used. Fetching a pack must not permanently duplicate every asset in JS memory and WASM memory.
- Keep individual URLs as a fallback with bounded retries and useful error reporting. Verify actual files and lengths; never silently substitute missing textures.

This work is a new implementation task. No pack-resolver integration was written or validated in this investigation.

### Loader/cache improvements

In `docker/web/site/launcher.js`:

- `fetchPart()` reads `res.clone().body`, leaving the other branch unread. Read `res.body` directly when no second consumer is needed. Response cloning can buffer data for the unread branch.
- Cache reads/writes should be best effort. Currently an awaited `cache.put()` failure can reject startup even after the download succeeded. A full/unavailable browser cache should degrade to network loading.
- Avoid a second `cache.match()` and avoid unnecessary buffer copies where possible. Measure memory before pursuing more complex zero-copy schemes.
- Do not block first-use readiness on optional disk-cache writes if they can safely finish in the background.
- Keep valid content-addressed parts across releases; ensure any per-part versioning also invalidates changed on-demand assets correctly.
- Add timings and clear loading/error states. A progress-bar change alone is not a performance fix.

These are code-review findings; cache failures and memory pressure were not reproduced as the cause of the reported deployment slowdown.

## Code locations and build constraints

- `docker/web/site/launcher.js`: preload downloading, Cache Storage, progress, filesystem initialization, and `getAsyncUrl` hook.
- `docker/prepare/bundle.py`: preload selection, content hashes, 16 MiB parts, and compression modes.
- `standalone/Dockerfile`: complete multi-stage build; the `customized-data` stage rebundles using `--compression boot`.
- `docker/web/Caddyfile`: immutable cache headers, precompressed order, and runtime encoding.
- `standalone/customize.py`, `engine-launcher.js`, `engine-shell.html`: preserve the tested branding removal and local-save-only launcher.
- Root `Dockerfile` is a symlink to `standalone/Dockerfile`.

Editing files copied into the compiler stage can invalidate the expensive audio conversion cache. For iteration, derive a separate optimization stage from already prepared data where feasible. Keep conversion/precompression out of runtime. Preserve the one-image deployment with no game-directory mounts.

## Validation required before release

1. Record cold and warm timings through the public deployment, with cache state and connection conditions documented.
2. Measure both **time to menu** and **time to playable world**. A faster button with a slower New Game is not success.
3. Verify intro/cutscenes, vehicle entry, radio, and driving into previously unseen areas while recording asset failures and loading pauses.
4. Check 404s, timeouts, failed `getAsyncUrl` lookups, and renderer errors. Capture the exact file and status for any missing texture.
5. Verify local saves survive reload, no cloud requests return, and branding remains removed.
6. Test cache-disabled and cache-write-failure paths, plus a warm repeat visit.
7. Build the x86-64 image and check runtime health, compression headers, CPU use during concurrent transfers, and absence of runtime mounts. Retain the multi-platform packaging workflow if it is updated.

The existing publication destinations are listed above, but **this investigation has not pushed new code/images or redeployed Launchpad**. Do not mistake the local experiment for the published artifact.

## Reproduction and evidence

Example live header check:

```sh
curl -sSI -H 'Accept-Encoding: br, zstd, gzip' \
  'https://gta-xo-su1mcue.apps.hello-xo.nl/data/vc-assets/local/models/gta3.img/wshxreflod.txd?v=4525c56b32bd32cc'
```

Example boot-transfer measurement (downloads to `/dev/null`, without decoding the response):

```sh
curl -sS -H 'Accept-Encoding: br' -o /dev/null \
  -w 'status=%{http_code} protocol=%{http_version} ttfb=%{time_starttransfer}s total=%{time_total}s bytes=%{size_download} speed=%{speed_download}\n' \
  'https://gta-xo-su1mcue.apps.hello-xo.nl/data/bundle/preload-4525c56b32bd32cc-0.bin'
```

Local evidence lives under ignored `.verification/perf/`, including `bench-8080.json`, `bench-18081.json`, `bench-remote.json`, `remote-complete.json` (the later readiness observation, not a claim of successful completion), `compression-samples.json`, captured response headers, and `remote-reused-connection.txt`. Browser traces are `.verification/perf-browser.jsonl` and `.verification/perf-baseline-browser.jsonl`. These files are local investigation artifacts, not part of a fresh clone; the material findings are recorded above.

The successful independent retry is recorded in `.verification/perf/remote-part4-retry.log` and `remote-part4-validation.headers`; its compressed body is `part4-retry.bin.zst`. The earlier `remote-part4-validation.log` records curl's unsupported-decoder error, a local tooling limitation rather than a server failure.

Primary references:

- [Caddy precompressed file serving](https://caddyserver.com/docs/caddyfile/directives/file_server)
- [Caddy response encoding](https://caddyserver.com/docs/caddyfile/directives/encode)
- [MDN: Response.clone and unread-branch buffering](https://developer.mozilla.org/en-US/docs/Web/API/Response/clone)
- [MDN: Cache.put](https://developer.mozilla.org/en-US/docs/Web/API/Cache/put)

## Implemented serving optimizations — follow-up, 2026-11-03

The user subsequently authorized implementation. The changes below are in the working tree and the locally built `vice-city-optimized:local` image. They have **not** been pushed to GitHub/the registry or deployed to Launchpad. The earlier smaller-core-only prototype remains rejected; this implementation retains the working model/world preload.

### Changes

- Deferred audio payloads from the upstream boot list: the 28,703,364-byte Flash FM track and one 4,077-byte MP3 sound. Both remain available through the existing engine audio path. No source game files, audio quality, textures, branding patches, or save implementation were changed.
- Boot data is now **98,206,867 decoded bytes across 1,915 files and 47 chunks**, capped at **2 MiB** each. Chunk filenames contain their full SHA-256, independent of the overall data version, so unchanged chunks can remain cached between releases.
- Added `docker/web/site/download.mjs`: four concurrent boot downloads, strict decoded-length checks, SHA-256 verification on HTTPS/localhost, up to three attempts, 30-second inactivity and 120-second per-attempt limits, corrupt-cache eviction, and cancellation of sibling requests after terminal failure. Plain HTTP on a remote/LAN address still checks lengths; Web Crypto requires a secure context.
- Cache access/write failures are nonfatal. Reads consume the original response rather than teeing an unread clone. Completed chunks copy into one preallocated boot buffer instead of retaining every chunk and then allocating a second whole bundle. Optional cache writes are outside the readiness path.
- The error overlay provides a functional **Retry** button; progress does not continue indefinitely after terminal failure.
- The final image build now precompresses streamed assets as well as boot data. It processed **6,436 compressible files: 565.4 MB raw to 308.2 MB using each file's smallest available encoding**. These totals include boot files and individual assets, not a single user session. Existing compressed audio is excluded by file extension.
- Caddy prefers Brotli, with Zstandard/gzip fallbacks. Only hashed boot paths and versioned asset URLs are immutable; unversioned paths revalidate. Access logs now include status, bytes and duration, supporting later Launchpad diagnosis.
- The overall asset version hashes **every asset**, including files outside the preload. Previously a changed streamed asset could retain the old immutable URL.
- The optional broad `?prefetch=1` mode remains opt-in; it now consumes response bodies and excludes `.adf` audio. No speculative region-pack resolver or CDN was introduced.

### Verification

- **12 Python regression tests** passed, including bundle reconstruction/hash validation, deferred audio, unchanged-chunk reuse, streamed-file cache invalidation, preparation safeguards and customization guards.
- **10 Node regression tests** passed, covering truncated/corrupt/oversized bodies, corrupt caches, cache read/delete/write failure, cache hits, retry limits, permanent versus transient errors, stalled bodies, cancellation, ordered assembly and bounded concurrency.
- The actual runtime image ran as UID 1000 with **no mounts**, limited to **one CPU and 4 GiB**, and passed its healthcheck.
- HTTP checks verified Brotli round trips against original bytes, immutable versus revalidated headers, and a **206 audio range response**. Sample `cop.dff`: 71,680 → 30,787 bytes (**57% smaller**); `wshxreflod.txd`: 20,480 → 14,114 bytes (**31% smaller**) in this build.
- Browser checks reached the original main menu, New Game, intro scenes and the playable street, with no observed asset failure during the gameplay sample. The player entered the Admiral and drove out of the alley **while Flash FM was still downloading**. The radio request subsequently completed and the engine logged `fetched audio\\flash.adf`. This demonstrates that radio deferral did not block movement in this test; it is not a claim of exhaustive gameplay or human audio-listening coverage.
- A write through the native game filesystem/IndexedDB sync survived reload and was read back, then removed. The cloud SDK remained absent.
- Browser fault injection returned a deliberately truncated boot response and rejected all **47 cache writes**. Startup still completed. A separate test returned repeated HTTP 503 responses, produced the Retry UI, then successfully reloaded after the fault was removed.
- A warm reload reached Start game in **1.155 seconds**, transferring **79,606 bytes** in parent-page resources, with the boot chunks reused from Cache Storage.

Cold comparisons use the same persistent Chrome DevTools connection, 750,000 download bytes/s (6 Mbps), 80 ms latency, disabled HTTP cache and cleared Cache Storage. The initial comparison recorded 109.679 seconds for the old build versus 91.707 seconds for the candidate, but build/unpack activity overlapped those runs. Use the subsequent idle comparison below for timings. The measured parent-page startup transfer fell from **74,164,760 to 44,405,865 bytes**, approximately **40% less**. This metric stops at Start game readiness; it does not include every later gameplay/audio transfer or measure time to playable world.

Final comparison after all building/unpacking had stopped:

| Build | Cold Start game readiness | Parent-page transferred bytes |
|---|---:|---:|
| Published baseline, local server | **99.449 s** | **74,164,760** |
| Optimized image, one-CPU / 4 GiB server | **59.689 s** | **44,405,865** |

This is approximately **40% less time and 40% fewer bytes** under the documented network throttle. The baseline server had no explicit CPU limit; the candidate did. Both ran on the same development host, served precompressed files, and used the same browser/controller. These are controlled local measurements, not a post-deployment Launchpad guarantee.

### Artifact and limits

The local image tag `vice-city-optimized:local` contains `linux/amd64` and `linux/arm64` variants under one manifest. The final index digest is `sha256:9708e72e2a8e77f0922fc0be2adf5ecd2ced35346b4857cf1261d15c134465d3`. Runtime/browser tests ran on x86-64. ARM64 was built and inspected, but this host cannot execute its binary (`exec format error`); ARM runtime testing requires a compatible host/emulator. The existing portable archive and published registry tag still contain the previous release.

Docker reported approximately **3.92 GB of local amd64 image storage** for that earlier build. Precompressed sidecars increase image/storage size in exchange for fewer transferred bytes and avoiding runtime compression of streamed assets. These changes cannot remove a hosting bandwidth limit or guarantee no streaming pause in every area. Recheck the public Launchpad URL after release, using the new request logs to investigate incomplete responses. The earlier remote truncation's precise origin remains unproven.

Local evidence (ignored by Git): `.verification/optimized-final-build.log`, `optimized-serving.json`, `optimized-browser.jsonl`, `optimized-driving-radio.png`, `optimized-retry.png`, `optimized-faults.json`, `optimized-warm.json`, and the idle benchmark JSON files. These artifacts remain local; material results are included in this document for a fresh clone.

The temporary optimized validation container and browser/controller were removed/stopped after testing. The existing local game container was left running unchanged.

## Further optimization assessment — fresh live check

After the first implementation, the user asked whether substantially faster Launchpad loading is possible. A fresh check of the public deployment still returned baseline manifest `4525c56b32bd32cc` (126,914,308 decoded preload bytes, eight parts), confirming that the local optimized image is not yet live.

A complete, isolated Brotli request for baseline boot part 0 returned HTTP/2 200: **7,341,970 bytes in 48.023532 seconds**, TTFB **1.064530 seconds**, effective rate **152,882 bytes/s**. Evidence: `.verification/further-serving/live-transfer.txt`, `live-part.headers`, and `live-manifest.json`. This measures the route between this machine and the public deployment, not a proven Launchpad bandwidth limit. At that rate, 10 MB alone takes approximately 65 seconds; extrapolating the optimized 44.4 MB startup gives approximately 290 seconds. Those are arithmetic illustrations, not measured optimized-production load times.

The next substantial code change should combine a small synchronous core with dependency groups for the first playable scene and bounded background prefetch for later scenes. The previous roughly 10.2 MB core experiment demonstrated menu startup only, and moved waiting into New Game. Instrument actual filesystem reads/model requests through intro, first-world entry and driving to derive required groups; do not treat the 10 MB figure as an established playable-world budget. Demand assets must take priority, retries must remain bounded, and persistent pack caching must avoid duplicate downloads and unbounded blob/WASM memory. Measure time to playable world and driving pauses, not just button readiness.

In parallel, compare identical requests from another client/network and, if available, an authorized direct-origin endpoint. Inspect proxy/egress limits and cache hits before attributing the rate to Launchpad. A CDN in front of the existing container can serve warm cached assets without another application image, but cannot fix a client's own bandwidth limit and cold edge misses still depend on the origin. Retain the complete offline-capable image as the origin.

For example, Cloudflare requires DNS proxying for Cache Rules; a domain/DNS configuration change is not achievable through this Docker image alone. Its default cacheable extensions include BIN but not the game's DFF/TXD/ADF formats, so configure explicit rules for versioned game asset paths, retain query-string versions, and verify actual cache hits, compression and range requests. Keep HTML and the manifest revalidated. See [Cloudflare Cache Rules](https://developers.cloudflare.com/cache/how-to/cache-rules/) and [default cache behavior](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/).

No further runtime changes, DNS changes or publication were performed during this assessment. A sub-10-second cold playable-world target would require a sufficiently small measured first-scene payload and substantially better effective delivery; it is not a supported guarantee from the current measurements.

### Next implementation and release steps

1. Preserve the tested optimized image as a comparison point. Record which image/manifest is live before each production measurement; the current optimized results are local, not deployed results.
2. Trace filesystem reads and asset requests through New Game, the opening scene, vehicle entry and driving. Use those traces to identify the synchronous core and first-scene dependencies, then build grouped downloads with bounded background prefetch. Keep all assets in the single image.
3. Measure identical files through the public proxy from multiple networks and directly from the origin where access is available. Use request byte counts/durations and platform metrics to distinguish client/network limitations from proxy or origin limitations.
4. If origin delivery is the bottleneck, configure an optional CDN in front of the existing container. Verify cold misses and warm hits separately, including versioned cache keys, model/texture caching, compression and audio range requests. CDN configuration requires access to the chosen domain/provider; no such configuration has been made.
5. Before release, compare cold and warm **time to playable world**, transferred bytes, asset failures and loading pauses along the same driving route. Recheck radio, local-save persistence and cache/retry failure paths. A smaller initial download is insufficient if New Game or driving stalls become worse.

The release decision should use measured public-deployment results. Further compression tuning alone cannot establish a few-second first load at the observed delivery rate.

## Adaptive streaming implementation — second optimization pass

This pass implements the next approach rather than deploying the first optimization. The user approved **automatically lighter textures on slow connections, with full quality available**. The original installation remains unchanged, and both profiles and all game data ship in one image. No CDN, DNS, external asset service, cloud save integration or engine recompilation was introduced.

### What changed

- Instrumented native filesystem reads through the menu, intro and first playable street. `standalone/startup-files.list` records the observed paths, including sounds requested through temporary engine filenames. This is a first-scene warmup list, **not an exhaustive dependency guarantee**: random pedestrians/vehicles and other save locations request additional files.
- `standalone/streaming.py` builds a 179-file synchronous core (24,376,543 decoded bytes) and two streaming profiles. Map configuration retains its referenced files; models and cutscene assets move to separate packs. The original complete asset snapshot remains available for direct-URL fallback.
- Core chunks and ordinary packs target 512 KiB decoded, with a larger single file kept intact. First-scene files follow traced read order. Later model/texture groups use IDE ownership; sound effects are grouped separately. SHA-256 filenames and Brotli/gzip sidecars let Caddy serve already-compressed bytes. All 17,565 original assets remain addressable.
- Supported world textures in lighter mode are reduced to at most 64 pixels; loading artwork to 256 pixels. Fonts/UI, geometry, collisions and uncommon formats are preserved. DXT1 alpha-cutout textures remain original. DXT3 alpha is explicitly encoded and checked. Reduced dictionaries retain their original padded file length to preserve archive-directory sector assumptions. **1,232 texture dictionaries change**, and Original profile contents remain byte-for-byte identical.
- Automatic selection measures an actual core chunk shared between profiles, then reuses it from the boot cache. Below approximately 750,000 encoded bytes/s it selects lighter textures; Save-Data also selects lighter. A cached probe reuses the previous automatic choice. The minimal screen offers Automatic / Lighter / Original; `?quality=low` and `?quality=full` override detection.
- `stream-assets.mjs` deduplicates concurrent requests, prioritizes demand over speculative work, verifies/caches packs, and limits decoded pack residency to 64 MiB. Downloaded related files can be inserted into the native filesystem ahead of demand, with a separate 48 MiB injection budget. This avoids repeated engine/network waits for already-prepared files; it is not a total game-memory limit.
- Finite first-scene preparation starts after core readiness, overlapping the Start screen and WASM initialization. Filesystem insertion waits until the engine finishes its core setup: inserting directories earlier caused upstream exclusive `mkdir` to fail, which browser testing caught and corrected. Random non-warmup models no longer cancel the rest of the first-scene queue. Demand can preempt background transfers.
- Owned blob URLs are released after XHR/fetch consumption, with bounded cleanup for abandoned URLs. Optional filesystem prefill failures do not reject valid demanded bytes. Pack failures fall back to the original individual asset. The previous broad `?prefetch=1` mode was removed to avoid duplicate full-quality downloads.
- Added `audio-assets.mjs` after observing duplicate requests for the same ambient recording. Concurrent consumers share one transfer, with independent returned bytes, a 32 MiB audio LRU and optional versioned Cache Storage. Audio uses separate jobs so long radio requests cannot occupy model-pack slots. Recordings remain unchanged; requests use low network priority, a 30-second stall limit, a 15-minute total limit and at most two attempts. Ordinary HTTP caching alone did not prevent the observed overlapping requests.
- The Docker build isolates pack generation from expensive audio conversion. Runtime remains one non-root Caddy process. Native IndexedDB saves are separate from download caches.

### Payloads

These are compressed pack budgets, **not total bytes needed to reach gameplay**:

| Profile | Core, Brotli bytes | Traced first-scene packs, Brotli bytes |
|---|---:|---:|
| Original | 7,530,872 | 12,308,214 |
| Lighter | 6,709,243 | 6,809,654 |

The lighter core is approximately 91% smaller than the published baseline's 74.16 MB parent-page startup transfer. Its core plus traced scene is 13.52 MB. Engine code/WASM, manifests, audio and randomly requested assets add to this. In particular, `audio/water.mp3` is a 5,061,294-byte, approximately 632-second ambient recording that the existing engine fetches whole; Brotli only reduced it by about 2%, so a speculative audio recompression change was not adopted. Radio also remains a whole-file, deferred download. These remaining engine behaviors prevent a credible promise of instant cold play or zero pauses everywhere at 150 KB/s.

### Validation and release status

- 17 Python tests passed, including texture dimensions, alpha, palette preservation and archive length. 22 Node tests passed across download integrity/retry/cache behavior, pack deduplication, preemption, bounded residency, filesystem prefill and its failure/budget paths, random-model warmup behavior, and audio coalescing, eviction, cancellation and recovery.
- Independently reconstructed and checked **2,740 unique generated packs** against their SHA-256/length descriptors and source files. Both profiles contain 16,273 packed/core files; all other original assets remain directly available. Original profile file bytes are identical; lighter differences are restricted to the permitted texture dictionaries.
- The container runs with no game-data mounts as UID 1000, limited to one CPU and 4 GiB, and passes its healthcheck. HTTP checks verified a compressed pack round trip, immutable hashed URLs, and a 206 audio range response. Browser tests cover the minimal quality selector and both automatic/explicit selection paths.

Final browser measurements and image identity are recorded below after idle verification. Development runs overlapping Docker unpack/export are not the final timing comparison. Evidence is retained under `.verification/streaming/` (ignored by Git); essential results belong in this handoff.

### Fresh public-path concurrency check

Repeated read-only identity-encoded byte-range requests against the still-published baseline, 262,144 bytes per request. One request completed in 2.896 seconds, four concurrent requests (1,048,576 bytes total) in 7.064 seconds, and another single request in 2.441 seconds. All returned valid HTTP 206 ranges. The four-request aggregate was approximately 148 KB/s including connection/TTFB; body-only rates were similar to the individual trials once their roughly one-second TTFB was excluded. This did **not** reveal a fourfold throughput opportunity from more parallel requests. It supports a shared bottleneck somewhere on this measured route, but does not identify a configured Launchpad cap or rule out client/network limitations. Evidence: `live-parallel.json` and `live-parallel.py`.

### Idle browser measurements

Both comparison runs used a persistent DevTools connection throughout each run, headless Chrome with software WebGL at 800×600 and `?fps=30`, disabled HTTP caching, cleared download Cache Storage, and the same automated New Game/intro-skip sequence. Screenshots were polled every two seconds to recognize the main menu and playable HUD. Time to playable street includes engine startup and the intro sequence, not solely downloading. Native rendering and random traffic also introduce run-to-run variation. The baseline server had no explicit CPU quota; the new server had one CPU / 4 GiB. No image builds/unpacks overlapped these final runs.

| Build, 750,000 bytes/s / 80 ms | Start button | Native menu | Playable street |
|---|---:|---:|---:|
| Published baseline, served locally | 105.024 s | 111.361 s | 163.615 s |
| New image, **Original textures** | 11.459 s | 22.076 s | 71.679 s |

That is approximately **56% less time to the playable street** (2.28× as fast), and 89% less time to Start button readiness, with Original texture contents preserved. These are controlled local observations, not a production deployment result. Evidence: `baseline-fast.json`, `idle-full-fast.json` and their world screenshots.


The final automatic-quality run at **150,000 bytes/s and 270 ms** selected Lighter: **48.957 s** to Start button, **86.081 s** to the native menu and **183.174 s** to the playable street. DevTools recorded **25,225,152 HTTP response-body bytes received** by that endpoint, including partial transfers; the two compressed pack budgets alone therefore understate the actual cold session. The Original-quality fast run received 35,038,523 body bytes. These totals use HTTP `Network.dataReceived.encodedDataLength`, excluding local blob deliveries and response headers. Both final runs had zero observed HTTP error statuses and zero uncaught JavaScript exceptions. Three deliberately preempted speculative pack requests in each run reported `ERR_ABORTED`; these are scheduler cancellations, not failed gameplay assets.

The slow run reused a simultaneous ambient recording request (`audio.shared` incremented); only one completed network request for `water.mp3` appears in its startup trace. Filesystem/cache fallback was also tested explicitly: injected HTTP 404s for a nonresident model pack and radio recording returned the original versioned asset URLs. The injected faults were removed before the final slow benchmark. A native IndexedDB filesystem marker survived reload and the image update, then was removed; `CloudSDK` remained undefined.


Warm revisit at the same 150,000 bytes/s / 270 ms reached Start in **1.813 s**, the native menu in **4.114 s**, and the playable street in **47.543 s**, including the intro sequence. No HTTP response-body bytes were received through the playable-street endpoint; HTTP validation headers still transferred. The game/audio caches came from prior play. Because cold tests deliberately disabled the browser HTTP cache, the shell/engine HTTP cache was explicitly primed before the warm test to represent a normal cached revisit. This does not imply a serverless/offline-installed browser app, nor that every unexplored part of the city is cached. Evidence: `final-warm.json`, `prime-http.json` and `final-warm-network.json`.

The player entered and moved the Admiral while radio was downloading at the slow throttle; the game subsequently rendered a hospital respawn in a different area. This is limited gameplay coverage, **not an exhaustive driving route or proof that every uncached area is pause-free**. The cached 5,061,294-byte water recording and 28,703,364-byte Flash FM recording were independently hashed in the browser and matched their prepared-source SHA-256 values exactly. Audio transfer coalescing was observed, and no owned blob URLs remained after completed deliveries. No human listening test is claimed.

### Current artifact and remaining boundary

The final multi-platform image index is **`sha256:1c8074a91c86c39ef7995b8d5f5443c6f2a765b9c6cbe282c9477571e8e1c2be`**, available locally as `vice-city-streaming:local` and `vice-city-standalone:local`. It contains `linux/amd64` and `linux/arm64` variants under one tag, with no second runtime service. AMD64 runtime/browser behavior was tested; ARM64 was built and inspected, not executed on this host. Docker reports approximately 6.51 GB for local unpacked AMD64 storage; the runtime file layers are approximately 3.65 GB. Both quality profiles, originals for fallback, legacy boot data and precompressed sidecars trade storage size for fast serving and portability.

The tested release targets `registry.xo.builders/gta-xo-su1mcue/app:latest` and `main` in the existing private GitHub repository. The image is published from the tested local tag without rebuilding. These local benchmarks do not establish the state or performance of the public Launchpad deployment. The existing local baseline container remains on its previous image and was not restarted. The temporary validation containers and dedicated browser/controller were removed/stopped after testing. The portable archive has been refreshed from the tested image and verified.

At the measured public-path throughput, the final cold session's approximately 25.2 MB of received bodies alone represents about 168 seconds at 150 KB/s. The measured 183-second cold playable-street result is therefore close to that transfer budget. This implementation substantially reduces startup work and repeat transfers, but a guarantee of instant cold play or zero new-area pauses needs faster delivery, a warm cache, or further engine/content changes. A CDN/direct-origin delivery improvement remains the next infrastructure step to investigate; no such service or configuration was added here. Retest the actual public deployment after release, including incomplete responses, cache hits, new-area driving, and native saves. Do not substitute Start-button timing for time to playable world.


Portable export: `standalone/out/vice-city-standalone.tar.gz`, **2,871,660,408 bytes** (about 2.87 GB / 2.67 GiB), tagged `vice-city-standalone:local`. Its tar structure, gzip CRC, SHA-256, and Linux AMD64/ARM64 configuration entries were checked. Both platform configurations retain UID 1000. The adjacent README matches the exported tag and current loading/quality behavior. Export checksum:

```text
3cd52e599a59317221a96428b10323a4ff6cdbeb3eeed21e48cbb30806c597ac  vice-city-standalone.tar.gz
```

Evidence: `archive-summary.json`, `package.log`, `runtime.json`, `audio-integrity.json`, `fallbacks.json`, `persistence.json`, `caddy-final.log`, the final benchmark/network JSON files and screenshots, plus the Python/Node test results. These generated evidence files are local and ignored by Git. This source revision and handoff accompany the tested image release. Rerun public-path measurements after Launchpad pulls the new image before attributing these local results to the live site. No explicit Launchpad redeploy is issued by the GitHub and registry publication commands.
