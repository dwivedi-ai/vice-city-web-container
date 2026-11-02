"""Build reVC's uint32-millisecond stream cache from the converted audio.

The engine opens streams synchronously during startup to determine duration.
Its cache must be preloaded when the actual audio is served on demand.
audio_streams.list follows the table in the checksum-pinned v9 engine.
"""

import argparse
import math
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    args = parser.parse_args()
    root = args.data / "vc-assets/local"
    names = [s for s in Path(__file__).with_name("audio_streams.list").read_text().splitlines()
             if s and not s.startswith("#")]
    missing = [name for name in names if not (root / name).is_file()]
    if missing:
        parser.exit(1, "audio cache: missing streams: " + ", ".join(missing) + "\n")

    def duration(name):
        value = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(root / name),
        ], text=True).strip())
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid duration for {name}: {value}")
        return max(1, round(value * 1000))

    with ThreadPoolExecutor(max_workers=4) as pool:
        durations = list(pool.map(duration, names))
    cache = root / "audio/sound.cache"
    temporary = cache.with_suffix(".tmp")
    temporary.write_bytes(struct.pack(f"<{len(durations)}I", *durations))
    temporary.replace(cache)
    print(f"audio cache: indexed {len(durations)} streams", flush=True)


if __name__ == "__main__":
    main()
