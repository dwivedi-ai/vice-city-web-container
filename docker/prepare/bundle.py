"""Turn compiled revcDOS data into a fast-to-serve layout.

Input:  <data>/vc-assets/local/...   (output of DOS.Zone's revcdos-data-compile.py)
Output: <data>/bundle/manifest.json
        <data>/bundle/preload-<hash>-<n>.bin   the boot files, concatenated and split
        *.zst / *.br / *.gz sidecars next to every compressible file, for Caddy's
        `file_server { precompressed }`.

The engine boots from the files in preload_files.list (handed over in one go
instead of ~2000 requests) and asks for everything else on demand.
"""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Already-compressed formats: sidecars would only waste disk.
INCOMPRESSIBLE = {".mp3", ".png", ".jpg", ".jpeg", ".zip", ".br", ".zst", ".gz", ".ogg", ".mp4"}
MIN_SIZE = 1024
MIN_SAVING = 0.05


def read_preload_list(path):
    seen = set()
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#") and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def compress_one(path, levels):
    src = path.read_bytes()
    made = []
    outputs = {
        ".gz": lambda: gzip.compress(src, compresslevel=9, mtime=0),
        ".br": lambda: subprocess.run(["brotli", "-c", "-q", str(levels["br"]), str(path)],
                                      check=True, capture_output=True).stdout,
        # Level <= 19 keeps the window at 8 MB, the most browsers accept for
        # Content-Encoding: zstd (so no --long / --ultra).
        ".zst": lambda: subprocess.run(["zstd", "-c", "-q", f"-{min(levels['zstd'], 19)}", str(path)],
                                       check=True, capture_output=True).stdout,
    }
    for ext, fn in outputs.items():
        if ext == ".br" and not shutil.which("brotli"):
            continue
        if ext == ".zst" and not shutil.which("zstd"):
            continue
        data = fn()
        if len(data) <= len(src) * (1 - MIN_SAVING):
            Path(str(path) + ext).write_bytes(data)
            made.append((ext, len(data)))
    return path, len(src), made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", help="folder that contains vc-assets/")
    ap.add_argument("--preload-list", required=True)
    ap.add_argument("--part-size", type=int, default=16 << 20)
    ap.add_argument("--brotli-level", type=int, default=11)
    ap.add_argument("--zstd-level", type=int, default=19)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()

    data = Path(args.data)
    assets = data / "vc-assets"
    if not (assets / "local").is_dir():
        sys.exit(f"bundle: {assets}/local not found - run the data compiler first")

    bundle = data / "bundle"
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir()
    for old in assets.rglob("*"):
        if old.suffix in (".gz", ".br", ".zst") and old.is_file():
            old.unlink()

    all_files = sorted(p.relative_to(data).as_posix() for p in assets.rglob("*") if p.is_file())
    available = set(all_files)

    wanted = read_preload_list(args.preload_list)
    preload = [p for p in wanted if p in available]
    missing = [p for p in wanted if p not in available]

    digest = hashlib.sha256()
    entries = []
    offset = 0
    for rel in preload:
        blob = (data / rel).read_bytes()
        digest.update(rel.encode() + b"\0" + blob)
        entries.append([rel, offset, len(blob)])
        offset += len(blob)
    total = offset
    version = digest.hexdigest()[:16]

    parts = []
    part_index = 0
    current = bytearray()

    def flush():
        nonlocal current, part_index
        if not current:
            return
        name = f"preload-{version}-{part_index}.bin"
        (bundle / name).write_bytes(current)
        parts.append({"url": f"bundle/{name}", "size": len(current)})
        part_index += 1
        current = bytearray()

    for rel, _, _ in entries:
        blob = (data / rel).read_bytes()
        view = memoryview(blob)
        while view:
            room = args.part_size - len(current)
            current += view[:room]
            view = view[room:]
            if len(current) >= args.part_size:
                flush()
    flush()

    manifest = {
        "version": version,
        "preload": {"size": total, "parts": parts, "files": entries},
        "files": all_files,
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))

    print(f"bundle: {len(all_files)} files, {len(preload)} preloaded "
          f"({total / 1e6:.1f} MB in {len(parts)} parts), version {version}")
    if missing:
        print(f"bundle: {len(missing)} preload entries not in your data (ok for other game versions), e.g. {missing[:3]}")

    targets = [p for p in list(bundle.glob("*.bin")) + [bundle / "manifest.json"]
               + [data / f for f in all_files]
               if p.suffix.lower() not in INCOMPRESSIBLE and p.stat().st_size >= MIN_SIZE]
    levels = {"br": args.brotli_level, "zstd": args.zstd_level}
    raw = packed = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for path, size, made in pool.map(lambda p: compress_one(p, levels), targets):
            raw += size
            packed += min([s for _, s in made], default=size)
    print(f"bundle: precompressed {len(targets)} files, {raw / 1e6:.1f} MB -> {packed / 1e6:.1f} MB best-case on the wire")


if __name__ == "__main__":
    main()
