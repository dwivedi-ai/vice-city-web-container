"""Build adaptive boot/stream packs from an already validated data snapshot.

Original game files and the full-quality snapshot are never modified. Low mode
reduces world textures to 64px and loading artwork to 256px; UI/fonts stay intact.
"""
import argparse
import gzip
import hashlib
import io
import json
import re
import struct
import subprocess
from collections import defaultdict
from pathlib import Path

from PIL import Image


def chunk(kind, version, payload):
    return struct.pack('<III', kind, len(payload), version) + payload


def children(blob, start=0, end=None):
    end = len(blob) if end is None else end
    while start < end:
        if start + 12 > end:
            raise ValueError('Truncated RenderWare header')
        kind, size, version = struct.unpack_from('<III', blob, start)
        stop = start + 12 + size
        if stop > end:
            raise ValueError('Invalid RenderWare size')
        yield kind, version, blob[start + 12:stop]
        start = stop


def dds(pixels, width, height, compression):
    fourcc = int.from_bytes(f'DXT{compression}'.encode(), 'little')
    return (b'DDS ' + struct.pack('<7I', 124, 0x81007, height, width, len(pixels), 0, 1)
            + bytes(44) + struct.pack('<8I', 32, 4, fourcc, 0, 0, 0, 0, 0)
            + struct.pack('<5I', 0x1000, 0, 0, 0, 0) + pixels)


def encode_dxt(image, compression):
    out = io.BytesIO()
    image.save(out, format='DDS', pixel_format=f'DXT{compression}')
    payload = bytearray(out.getvalue()[128:])
    if compression == 3:
        # Explicit four-bit alpha avoids encoder-specific alpha quantization.
        alpha = image.getchannel('A')
        offset = 0
        for y in range(0, image.height, 4):
            for x in range(0, image.width, 4):
                bits = 0
                for py in range(4):
                    for px in range(4):
                        value = alpha.getpixel((min(x + px, image.width - 1), min(y + py, image.height - 1)))
                        bits |= round(value / 17) << (4 * (py * 4 + px))
                payload[offset:offset + 8] = bits.to_bytes(8, 'little')
                offset += 16
    return bytes(payload)


def reduce_native(payload, limit):
    parts = list(children(payload))
    kind, version, data = parts[0]
    if kind != 1 or len(data) < 88 or struct.unpack_from('<I', data)[0] != 8:
        return payload
    raster, alpha, width, height, depth, levels, raster_type, compression = struct.unpack_from('<IIHHBBBB', data, 72)
    if max(width, height) <= limit or not levels:
        return payload
    # Preserve uncommon formats and DXT1 cutout alpha exactly.
    palette = b''
    if compression in (1, 3):
        if compression == 1 and alpha:
            return payload
    elif compression == 0 and depth == 8 and raster & 0x2000:
        palette = data[88:88 + 1024]
    else:
        return payload
    mips = []
    at = 88 + len(palette)
    for _ in range(levels):
        if at + 4 > len(data):
            raise ValueError('Truncated mip size')
        size = struct.unpack_from('<I', data, at)[0]
        at += 4
        if at + size > len(data):
            raise ValueError('Truncated mip data')
        mips.append(data[at:at + size])
        at += size
    skip = 0
    new_width, new_height = width, height
    while max(new_width, new_height) > limit:
        new_width, new_height = max(1, new_width // 2), max(1, new_height // 2)
        skip += 1
    if skip < len(mips):
        reduced = mips[skip:]
    else:
        if palette:
            im = Image.frombytes('P', (width, height), mips[0])
            reduced = [im.resize((new_width, new_height), Image.Resampling.NEAREST).tobytes()]
        else:
            im = Image.open(io.BytesIO(dds(mips[0], width, height, compression)))
            im = im.convert('RGBA' if compression == 3 else 'RGB')
            im = im.resize((new_width, new_height), Image.Resampling.LANCZOS)
            reduced = [encode_dxt(im, compression)]
    header = bytearray(data[:88])
    struct.pack_into('<HH', header, 80, new_width, new_height)
    header[85] = len(reduced)
    body = bytes(header) + palette + b''.join(struct.pack('<I', len(p)) + p for p in reduced)
    return chunk(1, version, body) + b''.join(chunk(k, v, p) for k, v, p in parts[1:])


def reduce_txd(blob, limit=64):
    kind, length, version = struct.unpack_from('<III', blob)
    if kind != 0x16 or length + 12 > len(blob):
        raise ValueError('Invalid TXD dictionary')
    result = []
    for k, v, payload in children(blob, 12, length + 12):
        if k == 0x15:
            payload = reduce_native(payload, limit)
        result.append(chunk(k, v, payload))
    out = chunk(kind, version, b''.join(result))
    # Archive directory sizes refer to original sectors. Keep their layout
    # contract; zero padding compresses away on the wire.
    if len(out) > len(blob):
        raise ValueError('Reduced texture unexpectedly grew')
    return out + bytes(len(blob) - len(out))


def referenced_maps(root):
    wanted = set()
    for name in ['gta_vc.dat', 'default.dat']:
        for line in (root / 'vc-assets/local/data' / name).read_text().splitlines():
            line = line.split('#')[0].strip().lower().replace('\\', '/')
            for token in line.split():
                if token.startswith('data/'):
                    wanted.add('vc-assets/local/' + token)
    return wanted


def build(root, output, startup):
    original = json.loads((root / 'bundle/manifest.json').read_text())
    files = original['files']
    available = set(files)
    references = referenced_maps(root)
    core = []
    for name, _, _ in original['preload']['files']:
        if name.startswith(('vc-assets/local/models/gta3.img/', 'vc-assets/local/anim/cuts.img/')) and not name.endswith('.col'):
            continue
        if name.startswith('vc-assets/local/data/maps/') and name not in references:
            continue
        core.append(name)
    core_set = set(core)
    initial = [s.strip() for s in startup.read_text().splitlines() if s.strip() in available and s.strip() not in core_set]
    # Only native asynchronous assets belong in packs; large music/dialogue
    # streams keep their existing individual/range-capable URLs.
    def packable(f):
        return f.startswith(('vc-assets/local/models/', 'vc-assets/local/anim/', 'vc-assets/local/audio/sfx.raw/'))
    initial = [f for f in initial if packable(f)]
    initial_set = set(initial)
    groups = defaultdict(list)
    # IDE ownership keeps neighboring map assets together rather than grouping
    # every model alphabetically across unrelated parts of the city.
    regions = {}
    for ide in (root / 'vc-assets/local/data').rglob('*.ide'):
        for line in ide.read_text(errors='replace').splitlines():
            bits = [s.strip().lower() for s in line.split(',')]
            if len(bits) >= 3 and bits[0].isdigit():
                for value, ext in [(bits[1], '.dff'), (bits[2], '.txd')]:
                    regions.setdefault('vc-assets/local/models/gta3.img/' + value + ext, ide.stem)
    for f in files:
        if f in core_set or f in initial_set or not packable(f):
            continue
        if '/sfx.raw/' in f:
            group = 'sfx-' + str(int(Path(f).stem) // 8) if Path(f).stem.isdigit() else 'sfx-other'
        else:
            group = regions.get(f, str(Path(f).parent))
        groups[group].append(f)
    output.mkdir(parents=True, exist_ok=True)
    written = set()
    def pack(blob):
        sha = hashlib.sha256(blob).hexdigest()
        name = f'pack-{sha}.bin'
        target = output / name
        if name not in written:
            target.write_bytes(blob)
            compressed = subprocess.check_output(['brotli', '-c', '-q', '9', str(target)])
            (output / (name + '.br')).write_bytes(compressed)
            (output / (name + '.gz')).write_bytes(gzip.compress(blob, compresslevel=9, mtime=0))
            written.add(name)
        return {'url': 'stream/' + name, 'size': len(blob), 'sha256': sha}
    profiles = {}
    boot_profiles = {}
    for quality in ('full', 'low'):
        def content(f):
            blob = (root / f).read_bytes()
            if quality == 'low' and f.endswith('.txd'):
                if '/models/gta3.img/' in f:
                    return reduce_txd(blob, 64)
                if '/txd/' in f:
                    return reduce_txd(blob, 256)
            return blob
        entries = []
        boot = bytearray()
        for f in core:
            blob = content(f)
            entries.append([f, len(boot), len(blob)])
            boot.extend(blob)
        parts = [pack(boot[i:i + (512 << 10)]) for i in range(0, len(boot), 512 << 10)]
        index = {}; packs = []; warmup = []
        def add_group(names, warm=False):
            current = bytearray(); pending = []
            def flush():
                if not pending:
                    return
                number = len(packs)
                packs.append(pack(current))
                if warm:
                    warmup.append(number)
                for f, start, size in pending:
                    index[f] = [number, start, size]
                current.clear(); pending.clear()
            for f in names:
                blob = content(f)
                if current and len(current) + len(blob) > 512 << 10:
                    flush()
                pending.append((f, len(current), len(blob)))
                current.extend(blob)
            flush()
        add_group(initial, True)
        for names in groups.values():
            add_group(names)
        manifest = {'schema': 3, 'quality': quality, 'version': original['version'] + '-stream1-' + quality,
                    'files': files, 'soundCache': original['soundCache'],
                    'preload': {'size': len(boot), 'files': entries, 'parts': parts},
                    'stream': {'packs': packs, 'files': index, 'warmup': warmup}}
        # Include topology/content in the version, not only the source snapshot.
        manifest['version'] = hashlib.sha256(json.dumps(manifest, separators=(',', ':')).encode()).hexdigest()[:16]
        name = f'manifest-{quality}.json'
        data = json.dumps(manifest, separators=(',', ':')).encode()
        (output / name).write_bytes(data)
        (output / (name + '.gz')).write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
        subprocess.run(['brotli', '-q', '9', '-f', '-k', str(output / name)], check=True)
        profiles[quality] = 'stream/' + name
        boot_profiles[quality] = parts
        wire = sum((output / (Path(p['url']).name + '.br')).stat().st_size for p in parts)
        first = sum((output / (Path(packs[i]['url']).name + '.br')).stat().st_size for i in warmup)
        print(f'{quality}: core={len(boot)} decoded/{wire} br; first-scene={first} br; {len(packs)} stream packs', flush=True)
    # Measure a real boot chunk shared by both qualities; cache it so the
    # adaptive selection does not add a throwaway bandwidth test.
    low_urls = {p['url'] for p in boot_profiles['low']}
    common = [p for p in boot_profiles['full'] if p['url'] in low_urls]
    probe = max(common, key=lambda p: (output / (Path(p['url']).name + '.br')).stat().st_size)
    (output / 'index.json').write_text(json.dumps({'profiles': profiles, 'probe': probe}))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('source', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--startup', type=Path, required=True)
    args = ap.parse_args()
    build(args.source, args.output, args.startup)
