#!/usr/bin/env bash
# Build and export one image containing the server, engine and game data.
set -euo pipefail
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$PROJECT_ROOT"
IMAGE=${IMAGE:-vice-city-standalone:local}
PLATFORMS=${PLATFORMS:-linux/amd64,linux/arm64}
case "${1:-}" in
    '')
        docker buildx build --platform "$PLATFORMS" --load --provenance=false \
            --build-arg "BROTLI_LEVEL=${BROTLI_LEVEL:-6}" \
            --build-arg "ZSTD_LEVEL=${ZSTD_LEVEL:-10}" \
            --build-arg "PREPARE_JOBS=${PREPARE_JOBS:-2}" \
            -t "$IMAGE" -f Dockerfile .
        ;;
    --export-only) docker image inspect "$IMAGE" >/dev/null ;;
    *) echo 'Usage: bash standalone/package.sh [--export-only]' >&2; exit 2 ;;
esac
mkdir -p standalone/out
ARCHIVE="$PROJECT_ROOT/standalone/out/vice-city-standalone.tar.gz"
umask 077
echo "Exporting all locally built platform variants of $IMAGE..."
docker image save "$IMAGE" | gzip -1 > "$ARCHIVE.partial"
mv "$ARCHIVE.partial" "$ARCHIVE"
(cd standalone/out && sha256sum vice-city-standalone.tar.gz > vice-city-standalone.tar.gz.sha256)
cp standalone/README.md standalone/out/README.md
echo "Ready: $ARCHIVE"
ls -lh "$ARCHIVE"
