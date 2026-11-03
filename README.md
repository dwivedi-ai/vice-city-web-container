# Vice City Web Container

A single-container browser runtime for a classic PC installation of GTA: Vice
City, with an asset-delivery layer designed for slow connections. The image
packages Caddy, a pinned revcDOS WebAssembly engine, and prepared game data.
The game runs in the browser; the container serves files.

This repository implements packaging, conversion helpers, adaptive texture packs,
and resilient downloading/caching. The game engine and HTML5 port are upstream
work by the [DOS.Zone team](https://dos.zone/revcdos).

**Status: experimental; upstream permissions unresolved.** The current build
uses a minimal launcher, removes upstream menu branding, and keeps saves local.
Those choices conflict with requirements in the upstream README. See
[attribution and license scope](THIRD_PARTY.md) before distributing or hosting
this configuration. No game assets or engine binaries are included in this repo.

## What improved

Measured locally with a cold browser cache, a 6 Mbps download throttle, 80 ms
latency, and **Original** textures:

| Milestone | Baseline | Optimized |
|---|---:|---:|
| Start button ready | 105.024 s | 11.459 s |
| Native game menu | 111.361 s | 22.076 s |
| Playable street, including intro | 163.615 s | 71.679 s |

That is **89% less waiting for Start** and **56% less time to the playable street**
in this comparison. These are individual controlled observations, not averages,
production measurements, or a promise of instant play.

The delivery layer combines:

- A small synchronous core and grouped model/texture downloads, with first-scene
  preparation overlapping engine startup.
- Automatic lighter textures on slow connections, with original quality available.
- Content-addressed chunks, integrity checks, bounded retries, and persistent caching.
- Demand-first scheduling and bounded model/audio caches; concurrent requests share
  downloads, and failed packs can fall back to individual assets.
- Build-time precompression and a non-root static server with a health check.

See the [engineering report](research/REPORT.md) for methodology, slow/warm results,
tradeoffs, and limitations. The improvements target loading and delivery, not FPS
or a rewrite of the engine. A cold visit at 150 KB/s still took about three minutes
to reach the world; faster public delivery remains an infrastructure question.

## Build and play

You need Docker with BuildKit and Docker Compose, a modern browser with WebAssembly
and WebGL support, and your own **classic PC Vice City installation**. The Definitive
Edition is unsupported. Unmodified files are the tested input; expanded map packs
can exceed engine limits.

Place the installation under `gamefiles/`, for example `gamefiles/GTA_VC/`, then run:

```sh
docker compose up -d --build
```

Open **http://localhost:8080**. The first build downloads upstream tooling and the
pinned engine, converts game data, and generates both texture profiles. It needs
internet access and several gigabytes of free space; temporary build layers can
use substantially more space than the exported image. Conversion never writes to
your source installation.

The final image runs as one container, without game-folder mounts or a preparation
service. To build/run it without Compose:

```sh
docker build -t vice-city-standalone:local .
docker run -d --name vice-city --restart unless-stopped -p 8080:8080 vice-city-standalone:local
```

Use `docker compose ps` to check readiness and `docker compose stop` to stop it.
Set `PORT=9000` in `.env` to change the Compose host port. Rebuild after replacing
source game files. The Dockerfile is the single build definition used by all paths.

## Playing and persistence

The launch screen has **Start game** and an Automatic / Lighter / Original texture
selector. Automatic selection uses measured transfer speed and the browser's
Save-Data preference. `?quality=low` and `?quality=full` override it; `?fps=30` caps
the frame rate. Game language is selected in the game's own options.

Saves live in the browser's IndexedDB, and settings in localStorage. There is no
cloud-save service. Clearing site data removes saves; another browser, hostname,
or port has separate storage. Download caches are independent of save data.

Use HTTPS for remote access so persistent asset caching, integrity verification,
and native gamepad features can use a secure context. Localhost also qualifies.
Keep `Content-Encoding`, `Vary: Accept-Encoding`, and version query strings intact
in any hosting proxy. A container cannot remove a hosting/network bandwidth limit.

## Portable image

```sh
bash standalone/package.sh
```

This exports Linux AMD64 and ARM64 variants under one image tag to
`standalone/out/vice-city-standalone.tar.gz`, with a checksum and run instructions.
The multi-platform export needs a containerd image store; for a single platform,
set `PLATFORMS=linux/amd64` or `PLATFORMS=linux/arm64`.

AMD64 runtime/browser behavior has been tested. ARM64 has been built and inspected,
but not runtime-tested. See [portable-package instructions](standalone/README.md).
Generated images contain game assets: keep them out of public registries, releases,
and CI artifacts.

## Development and checks

Use Python 3.11+ and Node.js 22+. No game installation is required for unit tests;
they use synthetic fixtures. Create a project-local environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node --test tests/test_*.mjs
docker compose config --quiet
```

Pillow is pinned to the version used by the Docker texture encoder. A missing test
dependency is an error, not a silently skipped texture suite. GitHub Actions runs
the suites on Python 3.11 and 3.14 with Node 22, using synthetic data only. CI does
not build or publish a game-containing image.

| Location | Responsibility |
|---|---|
| `Dockerfile` | Complete multi-stage image build |
| `docker/prepare/` | Source validation, conversion helpers, audio indexing, bundling |
| `docker/web/site/` | Browser launcher, chunk downloads, model/audio caching |
| `docker/web/Caddyfile` | Static serving, compression, cache policy, access logs |
| `standalone/` | Engine wrapper, texture/pack generation, validation and image export |
| `tests/` | Synthetic Python and JavaScript regressions |
| `research/` | Engineering results, methodology and compact benchmark evidence |

See [CONTRIBUTING.md](CONTRIBUTING.md) for validation expectations and
[SECURITY.md](SECURITY.md) for reporting vulnerabilities. Engine integration uses
checksum/anchor guards; an upstream upgrade requires reviewing and testing the
wrapper, not just changing the download URL. Base-image tags and OS package
versions are not fully locked, so builds are not bit-for-bit reproducible.

## License and attribution

Original project contributions are [MIT-licensed](LICENSE). That license does not
cover the game, downloaded engine, upstream-derived generated code, artwork/fonts,
or other dependencies. See [THIRD_PARTY.md](THIRD_PARTY.md) for the exact scope and
unresolved modification/distribution requirements.

HTML5 port by DOS.Zone: okhmanyuk-ev, caiiiycuk, and SerGen. This project is not
affiliated with DOS.Zone, Rockstar Games, or Take-Two.
