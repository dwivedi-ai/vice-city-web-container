# Attribution, license scope, and release status

## Project contributions

The [MIT license](LICENSE) covers original code and documentation contributed to
Vice City Web Container. It does not license GTA: Vice City, the revcDOS engine,
upstream code incorporated into generated files, downloaded artwork/fonts, or
other third-party components. A generated image is a collection of components
with separate terms; it is not wholly MIT-licensed.

## revcDOS

The HTML5 port is by the [DOS.Zone team](https://dos.zone/revcdos):
okhmanyuk-ev, caiiiycuk, and SerGen. This project supplies packaging, preparation,
and delivery code around their WebAssembly binary; it does not implement or
compile the game engine from source.

The build downloads converter resources from
[`Carter54git/revcdos` at `ae3c8fb`](https://github.com/Carter54git/revcdos/tree/ae3c8fb004d981e093d4759643f4fef171fea0ef)
and engine binaries from its
[v9 release](https://github.com/Carter54git/revcdos/releases/tag/v9).
Checksums are recorded in the root Dockerfile and `standalone/customize.py`.
Resources include the converter, preload list, `fronten1.txd`, and
`sansation.ttf`. The generated launcher incorporates upstream JavaScript;
the local wrapper's license does not replace the terms of that code.

The [upstream README at the pinned revision](https://github.com/Carter54git/revcdos/blob/ae3c8fb004d981e093d4759643f4fef171fea0ef/README.md)
requires attribution and a link, an enabled cloud-save integration, and its menu
logo. The current customization credits the authors but removes the logo/menu
footer and cloud integration. No exception or permission for those removals is
recorded here. Public availability of the binaries is not an unrestricted
open-source license.

**The upstream permission question remains unresolved.** Preparing this source
repository for review does not establish permission to distribute or host the
modified engine. Keeping the repository private also does not waive upstream
terms. Before a public release of this configuration, resolve the modification
and distribution permissions with the rights holders or use a compatible
alternative. This cleanup deliberately preserves the current game experience;
it is not a claim that the rights issue has been fixed.

## Game data and other dependencies

GTA: Vice City and its assets belong to their respective rights holders,
including Rockstar Games and Take-Two. Supply your own classic PC installation.
No game assets, engine binaries, or prepared packs are committed to this
repository. Keep installations, generated images, archives, and save data out of
public Git, Actions artifacts, GitHub Releases, and public registries. Ownership
of a game copy does not itself grant redistribution rights.

Build/runtime dependencies (including Debian, Alpine, Caddy, Python, FFmpeg,
Pillow, Brotli, and Zstandard) retain their own licenses and notices. The
Dockerfile identifies the packages and base images used. This document is a
scope and attribution record, not a complete image SBOM or legal clearance.

This project is not affiliated with Rockstar Games, Take-Two, or DOS.Zone.
