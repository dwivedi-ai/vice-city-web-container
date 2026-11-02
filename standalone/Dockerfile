# syntax=docker/dockerfile:1
# One self-contained image; conversion tools remain in build stages only.
# Converts an original GTA: Vice City PC install into revcDOS web data.
# Same converter DOS.Zone ships (revcdos-data-compile.py), minus Wine:
# see shims/wine.
FROM --platform=$BUILDPLATFORM debian:bookworm-slim AS compiler

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

COPY docker/prepare/shims/ /usr/local/bin/
COPY docker/prepare/*.py docker/prepare/*.sh docker/prepare/*.list /opt/prepare/
RUN chmod +x /usr/local/bin/wine /usr/local/bin/7z /usr/local/bin/ffmpeg /opt/prepare/prepare.sh

# Build-time only: original files are never copied into a runtime layer.
ARG BROTLI_LEVEL=6
ARG ZSTD_LEVEL=10
ARG PREPARE_JOBS=2
ENV COMPRESSION=boot
COPY standalone/validate_data.py /opt/prepare/validate_data.py
RUN --mount=type=bind,source=gamefiles,target=/gamefiles,ro \
    mkdir -p /data && /opt/prepare/prepare.sh && python3 /opt/prepare/validate_data.py /data

FROM compiler AS customized-data
COPY standalone/customize.py /opt/customize.py
RUN --mount=type=bind,source=gamefiles,target=/gamefiles,ro \
    python3 /opt/customize.py logo /data /gamefiles \
 && python3 /opt/prepare/bundle.py /data --preload-list /opt/revcdos/src/preload_files.list \
      --compression boot --brotli-level "$BROTLI_LEVEL" --zstd-level "$ZSTD_LEVEL" --jobs "$PREPARE_JOBS" \
 && python3 /opt/prepare/validate_data.py /data

FROM --platform=$BUILDPLATFORM alpine:3 AS engine
RUN apk add --no-cache curl unzip brotli zstd python3

# Official revcDOS binaries released by the DOS.Zone team, pinned by checksum.
ARG REVCDOS_RELEASE_URL=https://github.com/Carter54git/revcdos/releases/download/v9/vc-sky-9.zip
ARG REVCDOS_RELEASE_SHA256=e4a8147738304834624561a893182fd4555e75e75b6911ed2cc37c205f119bfa
RUN set -eu; \
    curl -fsSL -o /tmp/engine.zip "$REVCDOS_RELEASE_URL"; \
    echo "$REVCDOS_RELEASE_SHA256  /tmp/engine.zip" | sha256sum -c -; \
    mkdir /engine; unzip -q /tmp/engine.zip -d /engine; rm /tmp/engine.zip
COPY standalone/customize.py standalone/engine-shell.html standalone/engine-launcher.js /opt/customize/
RUN set -eu; python3 /opt/customize/customize.py engine /engine /opt/customize; \
    cd /engine; \
    for f in *.wasm *.js *.html *.list; do \
        gzip -9 -k "$f"; brotli -q 11 -k "$f"; zstd -19 -q -k "$f"; \
    done

# Both platform variants share the WASM/game assets and use native Caddy.
# No target-architecture commands are executed during the build.
FROM caddy:2-alpine AS server
FROM alpine:3 AS runtime
COPY --from=server /usr/bin/caddy /usr/bin/caddy
COPY --from=server /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=engine /engine /srv/engine
COPY docker/web/site/ /srv/
COPY docker/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=customized-data /data/bundle /srv/data/bundle
COPY --from=customized-data /data/vc-assets /srv/data/vc-assets
ENV SITE_ADDRESS=:8080 XDG_CONFIG_HOME=/tmp/config XDG_DATA_HOME=/tmp/data
WORKDIR /srv
USER 1000:1000
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/data/bundle/manifest.json || exit 1
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
