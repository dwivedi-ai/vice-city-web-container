# Converts an original GTA: Vice City PC install into revcDOS web data.
# Same converter DOS.Zone ships (revcdos-data-compile.py), minus Wine:
# see shims/wine.
FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 ffmpeg brotli zstd ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# DOS.Zone's official data compiler, pinned by commit and checksum.
ARG REVCDOS_COMMIT=ae3c8fb004d981e093d4759643f4fef171fea0ef
RUN set -eu; \
    base="https://raw.githubusercontent.com/Carter54git/revcdos/${REVCDOS_COMMIT}/src"; \
    mkdir -p /opt/revcdos/src; cd /opt/revcdos/src; \
    for f in revcdos-data-compile.py preload_files.list fronten1.txd sansation.ttf; do \
        curl -fsSL -o "$f" "$base/$f"; \
    done; \
    printf '%s\n' \
      "65444192746f870c2f2d8547533a1de8bf6b8fbfd10eb9971383ff26eb38ae53  revcdos-data-compile.py" \
      "35baf90e5a46585b4ff9141450cee9a43384eed66d13ca795b88438e6f22535f  preload_files.list" \
      "e0d2324d349aa217c26fee497c50621002f8194dab46cef39e3f4889368147a9  fronten1.txd" \
      "c0770982633d933a09da349cf0dde6cfd70d6f9d91f1df436410c4d014a3216d  sansation.ttf" \
      | sha256sum -c -; \
    touch adf2mp3.exe

# The RAW conversion rewrites sample rates in sfx.sdt. Do not let the parallel
# plain-file copy overwrite that generated index with the original one.
RUN python3 -c 'from pathlib import Path; p = Path("/opt/revcdos/src/revcdos-data-compile.py"); s = p.read_text(); old = "        else:\n            copy2(src_path, dst_path)"; assert s.count(old) == 1; p.write_text(s.replace(old, "        elif basename(src_path).lower() == \"sfx.sdt\":\n            return\n" + old))'

COPY shims/ /usr/local/bin/
COPY bundle.py prepare.sh fetch_game.py stage_game.py audio_cache.py audio_streams.list /opt/prepare/
RUN chmod +x /usr/local/bin/wine /usr/local/bin/7z /usr/local/bin/ffmpeg /opt/prepare/prepare.sh

VOLUME ["/data"]
ENTRYPOINT ["/opt/prepare/prepare.sh"]
