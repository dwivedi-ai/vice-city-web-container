# Vice City: one portable Docker image

The image contains the web server, customized revcDOS engine, minimal launcher,
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
The upstream hostname redirect is disabled for this self-hosted image.

This archive includes your game assets: keep it private rather than publishing it
as a public registry image.

## Build from your own installation

Put the classic PC Vice City installation under `gamefiles/`, either directly or
in a single subfolder. Run from the project root:

```sh
bash standalone/package.sh
```

The build checks the source layout, converts audio/models, generates the required
audio-duration cache, restores the original menu logo, builds and validates the boot bundle, and assembles the
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

HTML5 port by the [DOS.Zone team](https://dos.zone/revcdos). This custom build uses
a minimal launch page, the original game's menu logo, local saves, and a guarded
patch to remove the compiled menu footer. Engine upgrades require reviewing the
patch against the new binary; an unexpected checksum stops the build.
