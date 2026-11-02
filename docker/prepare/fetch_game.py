"""Download your own backup of the game (a .zip or .tar[.gz]) and unpack it.

    python3 fetch_game.py <url-or-google-drive-link> <dest-dir>

Google Drive: share the file as "Anyone with the link" and pass the share
link (https://drive.google.com/file/d/<id>/view?...) or just the file id.
Any other http(s):// or file:// URL is downloaded as-is.

Prints the path of the folder that contains models/ (the install folder).
Skips the download when <dest-dir> already holds this exact source.
"""

import html
import re
import urllib.error
import shutil
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

CHUNK = 1 << 20


def drive_id(src):
    for pattern in (r"/file/d/([\w-]{20,})", r"[?&]id=([\w-]{20,})", r"^([\w-]{25,})$"):
        m = re.search(pattern, src)
        if m:
            return m.group(1)
    return None


def log(msg):
    print(f"fetch: {msg}", file=sys.stderr, flush=True)


def stream_to(res, path):
    total = int(res.headers.get("Content-Length") or 0)
    done = 0
    next_report = 0
    with open(path, "wb") as out:
        while chunk := res.read(CHUNK):
            out.write(chunk)
            done += len(chunk)
            if done >= next_report:
                log(f"{done / 1e6:.0f} MB" + (f" / {total / 1e6:.0f} MB" if total else ""))
                next_report = done + (100 << 20)
    log(f"downloaded {done / 1e6:.1f} MB")


def download(src, path):
    fid = drive_id(src) if "://" not in src or "google.com" in src else None
    if fid is None:
        with urllib.request.urlopen(src) as res:
            return stream_to(res, path)

    url = f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"
    for _ in range(3):
        with urllib.request.urlopen(url) as res:
            if "text/html" not in res.headers.get("Content-Type", ""):
                return stream_to(res, path)
            page = res.read().decode("utf-8", "replace")
        # Large files get a "can't scan for viruses" page with a form to confirm.
        form = re.search(r'<form[^>]+action="([^"]+)"', page)
        fields = dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', page))
        if not form or not fields:
            break
        url = html.unescape(form.group(1)) + "?" + urllib.parse.urlencode(fields)
    sys.exit("fetch: Google Drive did not return the file. Make sure it is shared as "
             "'Anyone with the link' and the link points at a single .zip file.")


def extract(archive, dest):
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                target = (dest / info.filename).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    sys.exit(f"fetch: refusing unsafe path in archive: {info.filename}")
            z.extractall(dest)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(dest, filter="data")
            else:
                for m in t.getmembers():
                    target = (dest / m.name).resolve()
                    if not str(target).startswith(str(dest.resolve())) or m.issym() or m.islnk():
                        sys.exit(f"fetch: refusing unsafe entry in archive: {m.name}")
                t.extractall(dest)
    else:
        sys.exit("fetch: the download is not a .zip or .tar archive.")


def find_install(root):
    candidates = [p for p in [root, *root.rglob("*")] if p.is_dir()
                  and any(c.is_dir() and c.name.lower() == "models" for c in p.iterdir())]
    if not candidates:
        sys.exit("fetch: no folder with a models/ subfolder in the archive - zip the game's install folder itself.")
    return min(candidates, key=lambda p: len(p.parts))


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dest = sys.argv[1].strip(), Path(sys.argv[2])
    marker = dest / ".source"
    unpacked = dest / "unpacked"

    if marker.exists() and marker.read_text() == src and unpacked.is_dir():
        log("already downloaded, reusing it")
    else:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        archive = dest / "download.bin"
        log("downloading your game archive...")
        download(src, archive)
        log("unpacking...")
        unpacked.mkdir()
        extract(archive, unpacked)
        archive.unlink()
        marker.write_text(src)

    print(find_install(unpacked))


def run():
    try:
        main()
    except urllib.error.HTTPError as e:
        hint = " (not found or not shared: set sharing to 'Anyone with the link')" if e.code in (401, 403, 404) else ""
        sys.exit(f"fetch: download failed: HTTP {e.code}{hint}")
    except urllib.error.URLError as e:
        sys.exit(f"fetch: download failed: {e.reason}")


if __name__ == "__main__":
    run()
