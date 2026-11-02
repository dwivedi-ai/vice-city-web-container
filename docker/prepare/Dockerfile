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

COPY shims/ /usr/local/bin/
COPY bundle.py prepare.sh fetch_game.py /opt/prepare/
RUN chmod +x /usr/local/bin/wine /usr/local/bin/7z /opt/prepare/prepare.sh

VOLUME ["/data"]
ENTRYPOINT ["/opt/prepare/prepare.sh"]
