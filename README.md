# Vice City in your browser, self-hosted (revcDOS + Docker)

This runs the DOS.Zone team's [revcDOS](https://dos.zone/revcdos) on your own machine. revcDOS is reVC (the reverse-engineered Vice City engine) compiled to WebAssembly. The game data comes from **your own copy of GTA: Vice City for PC**. Nothing copyrighted is downloaded or baked into the images.

```
./gamefiles  (your install, read-only)
     │  prepare  (one-shot)
     │    DOS.Zone's revcdos-data-compile.py: .img unpacked, audio → MP3
     │    bundle.py: boot pack + zstd/br/gzip copies
     ▼
 docker volume "vcdata"  ──►  web  (Caddy)  ──►  http://localhost:8080
                                 engine/   official revcDOS v9 binaries (checksum-pinned)
                                 index.html + launcher.js   (our host page)
```

## Play

1. Copy your Vice City install folder into `./gamefiles/`. That is the folder with `gta-vc.exe`, `models/`, `audio/`, `data/` and so on. The Retail or Steam PC version works; the Definitive Edition does not. Alternatively, set `GAMEFILES=/path/to/Vice City`.
2. Run:
   ```sh
   docker compose up -d --build
   ```
   The first run converts the data, which takes a few minutes (`docker compose logs -f prepare`). Later runs skip this unless your game files change. `FORCE=1` forces a rebuild.
3. Open **http://localhost:8080**. Use `PORT=9000 docker compose up -d` to pick another port.

### Option: game files from your Google Drive

Instead of filling `./gamefiles/`, you can keep a zip of **your own** install on Google Drive:

1. Zip your Vice City install folder (on Windows: right-click the folder → *Send to* → *Compressed (zipped) folder*). `.tar.gz` works too.
2. Upload the zip to Google Drive. Right-click it → *Share* → *General access: Anyone with the link* → *Copy link*.
3. Start with the link (or put `GAME_URL=...` in `.env`):
   ```sh
   GAME_URL="https://drive.google.com/file/d/<id>/view?usp=sharing" docker compose up -d --build
   ```
   It is downloaded and unpacked once into the `vcsource` volume. The web server never serves that volume. Later starts reuse the download.
4. Once it has been downloaded, turn the Drive sharing back to *Restricted*. Anyone who has the link can download the file while it is shared.

`./gamefiles/` takes priority when it holds a game folder. `GAME_URL` also accepts any direct `https://` URL to an archive, for example one on your NAS.

URL options:

| Option | Effect |
|---|---|
| `?fps=30` | Frame cap without busy-waiting. The original physics are tuned for 30; uncapped can break some missions. |
| `?prefetch=1` | Once the game is running, download the remaining models and animations into the browser cache in the background, so they never cause a hitch. |
| `?lang=ru` | Russian UI text (DOS.Zone option). |

Saves are kept in your browser's IndexedDB. DOS.Zone's optional cloud saves need a js-dos key, entered on their start screen.

### Playing from another device

The revcDOS page only allows itself to run when the top page is on `localhost`, `192.168.0.*` or `dos.zone`; any other host redirects to dos.zone. That is their rule, and this setup leaves it alone. To play from another computer, forward the port with `ssh -L 8080:localhost:8080 your-server` and open `http://localhost:8080` there. The Gamepad API and Cache Storage also need a secure context, which `localhost` is.

## What makes it faster than the public mirrors

| | Typical mirror (e.g. quenq) | This setup |
|---|---|---|
| Engine (`index.wasm`, 7.6 MB) | brotli on the fly, 2.4 MB | stored brotli-11, **1.8 MB**, or zstd-19 |
| Boot data | 135 MB **uncompressed**, preloads all of `gta3.img` | only the boot file list (DOS.Zone says about 50 MB), stored zstd/br/gzip, a few parallel parts |
| Start of download | after you click play | **at page open**, while the start screen is showing |
| Repeat visit | Cache Storage | Cache Storage keyed by content hash. No network except a 304 on the manifest. |
| On-demand assets | `blob:` URLs that game.js never frees (memory grows all session) | direct URLs, `immutable` cache, nothing left in memory |
| Radio | 1 station, the rest silent stubs | all stations from your install |
| Frame cap | patched Emscripten loop | `?fps=N` |
| Compile tool chain | Wine + i386 (about 1 GB) | no Wine: `.adf` is an MP3 XOR'd with 0x22, so a 10-line shim replaces `adf2mp3.exe` |

## Layout

- `docker/prepare/`: converter image (Debian, ffmpeg, brotli, zstd). It pulls DOS.Zone's compiler at a pinned commit and checks it against checksums, and adds `bundle.py`, `prepare.sh`, `fetch_game.py` (Google Drive/URL download) and the `wine`/`7z` shims.
- `docker/web/`: Caddy image. It contains the revcDOS v9 release (pinned SHA-256) precompressed at build time, the `Caddyfile` and `site/` (the launcher).
- `research/REPORT.md`: how the public web ports work.

## Credits and terms

The HTML5 port is by the **DOS.Zone team** ([dos.zone/revcdos](https://dos.zone/revcdos)): okhmanyuk-ev, caiiiycuk and SerGen. They allow self-hosting if you credit them, keep cloud saves, and keep their logo in the menu. Their engine files are served unmodified, and the launcher shows the credit.

reVC is a community reverse-engineering project. This is not affiliated with Rockstar Games or Take-Two. Use your own legally owned game files, and keep it for personal use.
