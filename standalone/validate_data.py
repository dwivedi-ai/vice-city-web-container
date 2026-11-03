"""Check the standalone snapshot against its manifest before building the image."""

import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "bundle/manifest.json").read_text())
for name in manifest["files"]:
    if not (root / name).is_file():
        sys.exit(f"Missing asset: {name}")

version = hashlib.sha256()
source = hashlib.sha256()
size = 0
for name, offset, length in manifest["preload"]["files"]:
    data = (root / name).read_bytes()
    if offset != size or len(data) != length:
        sys.exit(f"Invalid boot entry: {name}")
    version.update(name.encode() + b"\0" + data)
    source.update(data)
    size += length
if version.hexdigest()[:16] != manifest["preload"].get("version", manifest["version"]):
    sys.exit("Boot data does not match the manifest version")

packed = hashlib.sha256()
packed_size = 0
for part in manifest["preload"]["parts"]:
    data = (root / part["url"]).read_bytes()
    if len(data) != part["size"]:
        sys.exit(f"Incomplete boot part: {part['url']}")
    if part.get("sha256") and hashlib.sha256(data).hexdigest() != part["sha256"]:
        sys.exit(f"Corrupt boot part: {part['url']}")
    packed.update(data)
    packed_size += len(data)
if packed_size != size or size != manifest["preload"]["size"] or packed.digest() != source.digest():
    sys.exit("Boot bundle does not match its source assets")
if manifest.get("schema") == 2:
    assets = hashlib.sha256()
    for name in manifest["files"]:
        with (root / name).open("rb") as source_file:
            assets.update(name.encode() + b"\0" + hashlib.file_digest(source_file, "sha256").digest())
    if assets.hexdigest()[:16] != manifest["version"]:
        sys.exit("Assets do not match the manifest version")
print(f"Validated {len(manifest['files'])} assets and {size / 1e6:.1f} MB of boot data")
