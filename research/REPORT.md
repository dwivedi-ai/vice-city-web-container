# Engineering report: delivering Vice City over slow connections

Measured 2026-11-03. This report describes the asset-delivery implementation in
source revision `6f97af1`, its controlled browser tests, and its remaining limits.
The [compact benchmark data](benchmarks.json) retains exact timing values and
source-record hashes. Later repository cleanup changes documentation, test setup,
and archive extraction; it is not a new gameplay benchmark.

## Result

The principal improvement was changing **when and how assets reach the engine**.
A smaller boot set alone moved waiting into New Game; it did not solve the problem.
Combining a small synchronous core with first-scene packs, demand-first downloads,
and filesystem prefill improved both startup and entry into the world.

At 750,000 download bytes/s (6 Mbps) and 80 ms simulated latency, with cold caches
and original-quality textures:

| Milestone | Baseline | Adaptive streaming | Reduction |
|---|---:|---:|---:|
| Start ready | 105.024 s | 11.459 s | 89.1% |
| Native menu | 111.361 s | 22.076 s | 80.2% |
| Playable street | 163.615 s | 71.679 s | 56.2% |

The playable-street comparison is **2.28× as fast**. This is a measured delivery
improvement while preserving original profile asset bytes, not an FPS improvement,
engine rewrite, production SLA, or average across repeated trials.

## Why the original delivery stalled

The baseline preloaded 126,914,308 decoded bytes across 1,917 files. Its browser
startup transfer was approximately 74.16 MB. That included a 28.7 MB Flash FM
recording and many models that were not all needed before Start could be enabled.
Large downloads made interruptions expensive; late individual asset requests then
introduced more waiting during play.

Public-path measurements ranged from approximately 150–250 KB/s with roughly
one-second time to first byte. One cold browser attempt ultimately failed after
several minutes. Four simultaneous 256 KiB byte-range requests shared about
148 KB/s aggregate throughput in a later probe, rather than multiplying capacity.
These observations establish a slow measured route, **not a proven Launchpad
bandwidth cap**. Client network, transit, proxy, and origin delivery were not
independently isolated.

## Implementation

### Prepare once, serve static files

The multi-stage Docker build converts audio/models, validates inputs and bundles,
and prepares compressed sidecars. The final image contains Caddy, the pinned
upstream WASM engine, both texture profiles, and original assets for fallback.
It runs as UID 1000 without game-data mounts or a second service. The game executes
in the browser, so adding server CPU does not directly accelerate its simulation.

The core contains 179 files and 24,376,543 decoded bytes. Map configuration retains
its required references; model/cutscene dependencies move into streaming packs.
Core chunks and ordinary packs target 512 KiB decoded, with an oversized individual
file kept intact. All 17,565 original assets remain addressable. Filesystem traces
provided the initial scene list; later groups use IDE model/texture relationships.

SHA-256 filenames allow unchanged chunks to survive releases in browser caches.
Only hashed paths and versioned asset URLs receive immutable cache headers.
Caddy serves Brotli/Zstandard/gzip sidecars where present. HTML and manifests
revalidate; hashes of streamed assets participate in version invalidation.

### Schedule around gameplay demand

First-scene preparation starts after core readiness and overlaps Start/menu/engine
initialization. Two pack downloads run concurrently; a demanded asset can preempt
speculative traffic. Requests for a common pack share a transfer. The downloader
validates decoded length and, in secure contexts, SHA-256 before accepting bytes.
It bounds retries, cancels siblings after a terminal boot failure, and tolerates
unavailable browser storage. Completed chunks can be reused after Retry.

Related files are inserted into the native filesystem once its initial directory
setup is complete. Inserting them earlier collided with the engine's exclusive
`mkdir` calls; browser testing exposed and corrected that integration issue.
Random non-warmup traffic models no longer cancel the finite first-scene queue.
Failed packs fall back to individual versioned assets, which may be full quality.

Decoded model packs have a 64 MiB LRU; speculative filesystem insertion has a
separate 48 MiB budget. These are separate limits, not a cap on total browser or
WASM memory. Temporary owned blob URLs are released after delivery.

### Adapt texture cost without altering the original installation

The launcher times a reusable core chunk and selects Lighter below roughly
750,000 encoded bytes/s, or when Save-Data is enabled. A cached probe can reuse the
previous automatic choice. Automatic, Lighter, and Original remain user-selectable.

Lighter reduces supported world textures to at most 64 pixels and loading artwork
to 256 pixels. Fonts/UI, geometry, collision data, alpha-cutout textures, and
unsupported formats are preserved. DXT3 alpha and palette preservation are tested.
Reduced dictionaries retain padded file length to preserve archive-sector
assumptions. Exactly 1,232 texture dictionaries change; Original file contents
remain byte-for-byte equal to prepared originals.

| Pack budget | Original | Lighter |
|---|---:|---:|
| Core, Brotli bytes | 7,530,872 | 6,709,243 |
| Traced first-scene packs, Brotli bytes | 12,308,214 | 6,809,654 |

The first-scene pack budget falls **44.7%**. These numbers exclude engine code,
manifests, ambient/radio audio, and unpredictable extra assets; they are not a
complete cold-start transfer budget.

### Share audio downloads

Ambient and radio requests can overlap. A separate audio loader coalesces requests,
returns independent bytes to consumers, and maintains a 32 MiB LRU plus optional
versioned Cache Storage. Long radio transfers do not occupy model-pack slots.
Audio remains unchanged; requests have bounded stalls, total duration, and retries.

In the final slow run, simultaneous requests shared one completed download of
`water.mp3`. Independently hashed browser copies of that recording (5,061,294 bytes)
and Flash FM (28,703,364 bytes) matched the prepared sources. No human listening
test is claimed. Both recordings still download whole; this engine behavior limits
how small a cold session can become.

## Slow connections and repeat visits

At 150,000 bytes/s and 270 ms simulated latency:

| Cache state | Selected textures | Start ready | Native menu | Playable street |
|---|---|---:|---:|---:|
| Cold | Automatic → Lighter | 48.957 s | 86.081 s | 183.174 s |
| Warm | Lighter | 1.813 s | 4.114 s | 47.543 s |

The cold run received **25,225,152 HTTP response-body bytes** through the
playable-street endpoint, including partial transfers. At 150 KB/s, those bytes
alone imply about 168 seconds of transfer. That explains why the optimized session
still cannot be instant. The faster Original-quality run received 35,038,523 bytes;
that cross-run difference is not a controlled texture-only comparison.

The warm run received zero HTTP response-body bytes through that endpoint; HTTP
validation headers still transferred. Its world timing includes engine startup
and the intro sequence. Game/audio caches came from prior play. Since cold tests
explicitly disabled HTTP caching, the shell/engine HTTP cache was deliberately
primed before the warm test. This result does not imply an offline-installed app
or that every unvisited area has already been cached.

## Method and verification

- Headless Chrome, software WebGL, 800×600, `?fps=30`, a persistent DevTools
  connection, and the same New Game/intro-skip sequence for both comparison runs.
- HTTP cache disabled and Cache Storage cleared for cold measurements. Screenshots
  polled every two seconds to recognize menu/world endpoints, so millisecond
  recording precision is not millisecond endpoint accuracy.
- Both servers on the same development host. Candidate limited to one CPU / 4 GiB;
  baseline had no explicit CPU quota. No concurrent builds/unpacks during final
  comparison. Native rendering and random traffic introduce variation.
- One reported final run per condition, not a distribution or confidence interval.
- Original implementation verification: 17 Python and 22 JavaScript tests passed.
  Later extraction regressions and CI are repository-hardening work, not evidence
  of new runtime performance.
- Independently reconstructed 2,740 unique packs and checked hashes, lengths, and
  profile contents. Verified compressed HTTP round trips, cache headers, and 206
  audio ranges. Injected model-pack/audio 404s exercised direct-URL fallback.
- Final cold runs observed no HTTP error statuses or uncaught JavaScript exceptions.
  Three aborted speculative requests per run were intentional preemptions.
- Browser checks reached New Game, vehicle entry/movement while radio downloaded,
  and a hospital respawn. A native IndexedDB marker survived reload/image update.
  This is limited gameplay coverage, not a full-city, every-mission, or actual
  in-game save-menu verification campaign.
- AMD64 runtime tested; ARM64 built and inspected, not executed.

The tested multi-platform image index was
`sha256:1c8074a91c86c39ef7995b8d5f5443c6f2a765b9c6cbe282c9477571e8e1c2be`.
The private portable archive was 2,871,660,408 bytes. Keeping originals, two texture
profiles, legacy boot fallback, and compressed sidecars trades storage for delivery
speed. The repository contains no image or asset payloads.

Raw test profiles, duplicated asset trees, and large logs were removed during local
cleanup. Small evidence records were retained locally; selected scalar results
and their source hashes are committed in `benchmarks.json`. These summaries are
not a replacement for an independently rerunnable full browser harness.

## Reproduce and extend

1. Supply your own classic game installation and build the image with the root
   Dockerfile. Record image digest, source revision, browser version, platform,
   quality, CPU/memory constraints, and exact network settings.
2. Use an isolated browser profile. Clear both HTTP and download caches for a cold
   run; preserve native save data separately if it matters. Record Start readiness,
   menu, and first playable HUD with the same input/intro sequence.
3. Collect HTTP body bytes (including interrupted requests), error statuses,
   exceptions, scheduler cancellations, and gameplay pauses. Resource Timing
   encoded sizes alone do not prove network transfer on a cached revisit.
4. Repeat under 750,000 bytes/s / 80 ms and 150,000 bytes/s / 270 ms, then repeat with
   deliberately warm caches. Run multiple trials before drawing statistical claims.
5. Repeat through the actual hosting URL after deployment. Verify response lengths,
   cache keys, compression and ranges. Compare another client/network and, where
   authorized, a direct-origin path to isolate the bottleneck.
6. Drive through uncached areas, change radio stations, exercise saves, and test
   cache/retry failure paths. Faster Start readiness alone is not success.

The largest remaining opportunity is faster effective delivery, potentially through
an appropriately configured asset CDN. That requires measuring cold misses and
warm hits, preserving query-string versions and content encodings, and verifying
range behavior. No CDN/DNS change or new serving service was added here.

Engine-side progressive audio, broader trace coverage, and finer texture budgets
may reduce first-use cost further, but are not implemented or benchmarked claims.
The current data does not establish pause-free play everywhere or optimized
Launchpad production performance.

## Scope and provenance

This work optimizes packaging and delivery around DOS.Zone's revcDOS engine.
It is not an original port, a general DOS emulator, or an engine source release.
The current branding/cloud modifications are preserved by request. Their upstream
permission requirements remain unresolved; see [THIRD_PARTY.md](../THIRD_PARTY.md).
Public-source preparation must not be presented as distribution clearance.

Implementation references: [root Dockerfile](../Dockerfile),
[pack builder](../standalone/streaming.py),
[chunk downloader](../docker/web/site/download.mjs),
[stream cache](../docker/web/site/stream-assets.mjs), and
[audio cache](../docker/web/site/audio-assets.mjs).

Primary background references: [Caddy precompressed serving](https://caddyserver.com/docs/caddyfile/directives/file_server),
[MDN Cache Storage](https://developer.mozilla.org/en-US/docs/Web/API/CacheStorage),
and [upstream revcDOS](https://github.com/Carter54git/revcdos).
