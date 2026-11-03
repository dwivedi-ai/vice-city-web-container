# Vice City: one portable Docker image

The image contains the web server, pinned revcDOS engine, minimal launcher,
and prepared game data. It needs no game-folder mount, data volume, preparation
container, or additional image at runtime. The default exported package includes
Linux x86-64 (`amd64`) and ARM64 variants under one image tag.

## Load and run on another machine

Copy the archive and checksum together, then run:

```sh
sha256sum -c vice-city-standalone.tar.gz.sha256
docker load -i vice-city-standalone.tar.gz
docker run -d --name vice-city --restart unless-stopped -p 8080:8080 vice-city-standalone:local
```

Open **http://localhost:8080**, or **http://SERVER-IP:8080** from another device.
Use `-p 9000:8080` to choose a different host port. The container should become
`healthy` within about 20 seconds. Stop/start it with `docker stop vice-city`
and `docker start vice-city`.

Use Docker Engine 29+ or current Docker Desktop with its containerd image store
for the multi-platform package. On Windows/macOS, Docker Desktop must be running
Linux containers. Other CPU architectures need emulation or their own build;
this does not turn the game into a native Windows container or mobile app.
The game runs in the browser, so the Docker host does not need a GPU. The client
needs a modern browser with WebAssembly and WebGL support.
[Docker's multi-platform documentation](https://docs.docker.com/build/building/multi-platform/)
describes host support.

The game works without internet access after loading the image. Start it with the
**Start game** button. There is no cloud-save service, account prompt, or external
save SDK. Local saves live in this browser's IndexedDB storage; clearing site
data deletes them, and another browser or hostname has a separate save store.
For remote access, HTTPS through a reverse proxy enables
secure-context features such as native gamepads and persistent asset caching.

This archive includes your game assets: keep it private rather than publishing it
as a public registry image.

## Build from your own installation

Put the classic PC Vice City installation under `gamefiles/`, either directly or
in a single subfolder. Run from the project root:

```sh
bash standalone/package.sh
```

The build checks the source layout, converts audio/models, generates the required
audio-duration cache, builds and validates the boot bundle, and assembles the
runtime image. Conversion tools exist only in build stages. Both CPU variants
share the same architecture-independent game assets; conversion runs on the
build machine's native CPU.

The archive, SHA-256 checksum and these instructions are written to
`standalone/out/`. To export an image already built and tested locally:

```sh
bash standalone/package.sh --export-only
```

For a host-only build using an older Docker image store:

```sh
PLATFORMS=linux/amd64 bash standalone/package.sh
```

Use `linux/arm64` instead on an ARM64 host. `IMAGE`, `BROTLI_LEVEL`, `ZSTD_LEVEL`
and `PREPARE_JOBS` can also be set when building.

## Serving and loading

The image precompresses boot data and streamed models/textures during the build.
Caddy prefers Brotli, with Zstandard/gzip fallbacks; no compression tools run in
the serving container. Already compressed radio/audio is left alone.

Startup loads a small core; the first scene and later model/texture groups use
separate content-addressed packs. The launcher measures a real reusable boot
chunk and automatically selects lighter textures below about 6 Mbps. Choose
**Original** on the launch screen (or `?quality=full`) to keep full texture quality;
`?quality=low` forces lighter textures. Low mode reduces supported world textures
to 64 pixels and loading artwork to 256 pixels, preserving fonts, UI, models,
collision data, alpha-cutout textures and the source game files.

Boot chunks are capped at 512 KiB with four concurrent downloads. Stream packs
usually contain up to 512 KiB decoded data (a larger single file stays intact),
with two concurrent downloads and demand taking priority over background work.
The loader fills the native filesystem with related files before the engine asks
for them. Its decoded pack cache is limited to 64 MiB, and speculative filesystem
injection to 48 MiB; the engine also maintains its own loaded assets. Temporary
blob URLs are revoked after use. Radio remains on demand. Concurrent requests
for the same audio share one download; a separate 32 MiB memory cache and optional
`vc-audio` disk cache reuse recordings without changing their quality. Audio does
not occupy model-pack worker slots. Long audio requests have a 15-minute total
limit, a 30-second stall limit and at most two attempts.

Downloads check decoded length and SHA-256 on HTTPS/localhost. Interrupted
chunks retry up to three attempts; stalled transfers time out after 30 seconds
without data (120 seconds maximum per attempt). A final boot failure offers Retry,
reusing completed cached chunks. Cache Storage failures do not prevent play.
These caches are separate from native local saves. Pack failure falls back to
the original individual asset, so that asset can use full texture quality.

Every asset contributes to the data version, including files outside the boot
preload. Only hashed boot/stream paths and versioned asset URLs receive immutable cache
headers. Other URLs revalidate. Keep `Content-Encoding`, `Vary: Accept-Encoding`,
and query strings intact in any hosting proxy/CDN. The image cannot override a
hosting bandwidth limit; measure delivery through the public URL after release.

The root `Dockerfile` is the only build definition. For source-checkout tests,
follow `README.md`: create `.venv`, install `requirements-dev.txt`, then run both
the Python and Node suites. Texture dependencies are required, not optional.
Browser validation should include cold/warm startup, New Game, entering
vehicles/radio, driving, and local saves.

HTML5 port by the [DOS.Zone team](https://dos.zone/revcdos). Engine upgrades
require reviewing the integration against the new binary; an unexpected checksum
stops the build.

## License scope

The source repository licenses only original project contributions under MIT.
The engine, upstream-derived generated launcher, and game assets retain separate
terms. See `THIRD_PARTY.md` in the source checkout for attribution and license scope.
