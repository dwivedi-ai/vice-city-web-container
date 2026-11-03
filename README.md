# Vice City in one Docker image

Build a self-contained browser version of Vice City from your classic PC game
installation. The final image includes Caddy, the pinned revcDOS WebAssembly
engine, the launcher and all converted game data. One image and one container
are sufficient; no game files or volumes are mounted when running it.

## Build and play locally

Place your installation in `gamefiles/` (a nested folder such as
`gamefiles/GTA_VC/` is detected), then run:

```sh
docker compose up -d --build
```

Open **http://localhost:8080**. The first build converts the audio and models;
subsequent starts use the data baked into the image. See build progress with
`docker compose build --progress plain`. Check readiness with `docker compose ps`
and stop with `docker compose stop`. Set `PORT=9000` in `.env` to change the host
port. Rebuild after replacing your game files.

Use an unmodified classic PC installation, not the Definitive Edition. Preparation
normalizes filename casing, supports separate Radio/Sound directories, and never
writes to your source installation. Some expanded map packs exceed revcDOS limits;
clean original files provide the most reliable compatibility.

## Create a portable package

```sh
bash standalone/package.sh
```

This builds one image tag with Linux x86-64 and ARM64 variants and exports it,
including every required layer, to `standalone/out/vice-city-standalone.tar.gz`.
A checksum and run instructions accompany it. The multi-platform build requires
a containerd-backed Docker image store (Docker Engine 29+ or current Docker Desktop).

On the destination machine:

```sh
docker load -i vice-city-standalone.tar.gz
docker run -d --name vice-city --restart unless-stopped -p 8080:8080 vice-city-standalone:local
```

No preparation service, game-folder mount or build tools are needed there.
See [the portable-package instructions](standalone/README.md) for verification,
architecture support, remote access and build options.

The image works at localhost, server IPs and custom hostnames. Use HTTPS for remote
browser features that require a secure context, including native gamepads and
persistent asset caching. The launch screen has a single **Start game** button.
Saves stay in this browser's IndexedDB storage; settings stay in localStorage.
There is no account, cloud-save SDK, or remote save service. Clearing site data
also removes local saves, and changing hostname/port uses a separate save store.

The launcher automatically uses lighter world textures on slow connections.
Choose **Original** in the texture selector to keep full quality. URL options:
`?quality=low` or `?quality=full` override automatic selection; `?fps=30` caps
rendering at 30 FPS. Opening-scene packs prepare in the background, and later
assets load in related groups. Game language can be changed in its options.

## Development

`standalone/Dockerfile` is the complete multi-stage build. `docker/prepare/`
contains the conversion and bundling scripts, and `docker/web/` contains the
launcher and Caddy configuration. The older Dockerfiles under those directories
are not used by the single-image Compose or packaging workflow.

Run regression checks with `python3 -m unittest discover -s tests -v`.

The HTML5 port is by the [DOS.Zone team](https://dos.zone/revcdos): okhmanyuk-ev,
caiiiycuk and SerGen. This custom build replaces the launch page, restores the
original game logo, removes the cloud integration, and blanks the compiled menu
footer. `standalone/customize.py` verifies the pinned v9 WASM checksum before
editing only its footer text bytes; it preserves binary sizes and addresses.
Review these patches when changing engine releases. The modified logo is bundled
under a new content hash so browsers do not reuse the previous boot assets.

This is not affiliated with Rockstar Games or Take-Two. Use your own legally owned
game data and keep the resulting image private; it contains those game assets.
