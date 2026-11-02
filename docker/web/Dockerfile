# Static web server: DOS.Zone's revcDOS engine + our launcher, served by Caddy.
# Game data is not baked in; it is mounted at /srv/data (see docker-compose.yml).
FROM alpine:3.20 AS engine
RUN apk add --no-cache curl unzip brotli zstd

# Official revcDOS binaries released by the DOS.Zone team, pinned by checksum.
ARG REVCDOS_RELEASE_URL=https://github.com/Carter54git/revcdos/releases/download/v9/vc-sky-9.zip
ARG REVCDOS_RELEASE_SHA256=e4a8147738304834624561a893182fd4555e75e75b6911ed2cc37c205f119bfa
RUN set -eu; \
    curl -fsSL -o /tmp/engine.zip "$REVCDOS_RELEASE_URL"; \
    echo "$REVCDOS_RELEASE_SHA256  /tmp/engine.zip" | sha256sum -c -; \
    mkdir /engine; unzip -q /tmp/engine.zip -d /engine; rm /tmp/engine.zip /engine/host.html; \
    cd /engine; \
    for f in *.wasm *.js *.html *.list; do \
        gzip -9 -k "$f"; brotli -q 11 -k "$f"; zstd -19 -q -k "$f"; \
    done

FROM caddy:2-alpine
COPY --from=engine /engine /srv/engine
COPY site/ /srv/
COPY Caddyfile /etc/caddy/Caddyfile
ENV SITE_ADDRESS=:8080
EXPOSE 8080
