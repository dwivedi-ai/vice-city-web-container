#!/bin/sh
# One-shot job: original game files -> web data (/data).
# Game files come from the /gamefiles mount, or - when that is empty and
# GAME_URL is set - from an archive of your own install (e.g. Google Drive).
# Skips the work when /data already matches the current game files.
set -eu

IN=${IN:-/gamefiles}
OUT=${OUT:-/data}
SOURCE=${SOURCE:-/source}
COMPILER=${COMPILER:-/opt/revcdos/src}
BUNDLER=${BUNDLER:-/opt/prepare/bundle.py}
FETCHER=${FETCHER:-/opt/prepare/fetch_game.py}
STAGER=${STAGER:-/opt/prepare/stage_game.py}
AUDIO_CACHE=${AUDIO_CACHE:-/opt/prepare/audio_cache.py}

if INSTALL=$(python3 "$STAGER" "$IN"); then
    IN=$INSTALL
else
    RESULT=$?
    [ "$RESULT" -eq 1 ] || exit "$RESULT"
    if [ -n "${GAME_URL:-}" ]; then
        IN=$(python3 "$FETCHER" "$GAME_URL" "$SOURCE")
    else
        echo "prepare: no game files. Either copy your own GTA: Vice City PC install into ./gamefiles" >&2
        echo "         (the folder with gta-vc.exe, models/, audio/, data/), or set GAME_URL to a" >&2
        echo "         Google Drive link of a .zip of that folder (see README)." >&2
        exit 1
    fi
fi
echo "prepare: using game files in $IN"

# Cheap fingerprint of the input: paths, sizes and mtimes.
STAMP=$({
    (cd "$IN" && find . -type f -printf '%p %s %T@\n' | sort)
    sha256sum "$0" "$STAGER" "$BUNDLER" "$COMPILER/revcdos-data-compile.py" "$COMPILER/preload_files.list"
    sha256sum "$AUDIO_CACHE" "$(dirname "$AUDIO_CACHE")/audio_streams.list"
} | sha256sum | cut -c1-16)
if [ "${FORCE:-0}" != "1" ] && [ -f "$OUT/.ready" ] && [ "$(cat "$OUT/.ready")" = "$STAMP" ]; then
    echo "prepare: data is up to date ($STAMP), nothing to do."
    exit 0
fi

STAGED=$(mktemp -d)
trap 'rm -rf "$STAGED"' EXIT HUP INT TERM
python3 "$STAGER" "$IN" "$STAGED"
rm -f "$OUT/.ready"
echo "prepare: compiling game data with DOS.Zone's revcdos-data-compile.py (MP3 transcoding takes a few minutes)..."
python3 -u "$COMPILER/revcdos-data-compile.py" "$STAGED" "$OUT"

echo "prepare: indexing audio durations for streaming..."
python3 "$AUDIO_CACHE" "$OUT"

echo "prepare: bundling and precompressing..."
python3 -u "$BUNDLER" "$OUT" --preload-list "$COMPILER/preload_files.list" \
    --brotli-level "${BROTLI_LEVEL:-11}" --zstd-level "${ZSTD_LEVEL:-19}" \
    --jobs "${PREPARE_JOBS:-2}" --compression "${COMPRESSION:-all}"

echo "$STAMP" > "$OUT/.ready"
echo "prepare: done."
