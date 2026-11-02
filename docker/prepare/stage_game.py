"""Locate a PC install and build a lowercase, read-only symlink view for reVC."""

import argparse
import sys
from pathlib import Path


def find_install(root):
    def is_install(path):
        names = {p.name.lower() for p in path.iterdir() if p.is_dir()}
        return {"models", "data", "audio", "anim"} <= names

    if not root.is_dir():
        return None
    if is_install(root):
        return root
    candidates = [p for p in root.iterdir() if p.is_dir() and is_install(p)]
    if len(candidates) > 1:
        raise ValueError("multiple game installs found; set GAMEFILES to the intended install")
    return candidates[0] if candidates else None


def stage(install, dest):
    def merge(src, dst):
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for child in sorted(src.iterdir()):
                merge(child, dst / child.name.lower())
        else:
            if dst.exists():
                raise ValueError(f"conflicting game files: {dst} and {src}")
            dst.symlink_to(src.resolve())

    # Windows plugins, executables and mod loaders cannot run in the WASM engine.
    folders = {p.name.lower(): p for p in install.iterdir() if p.is_dir()}
    for name in ("anim", "audio", "data", "models", "text", "txd", "skins", "mp3"):
        if name in folders:
            merge(folders[name], dest / name)
    # Some PC installs move these out of Audio; reVC expects them there.
    for name in ("radio", "sound"):
        if name in folders:
            merge(folders[name], dest / "audio")
    required = ("models/gta3.img", "models/gta3.dir", "anim/ped.ifp",
                "data/gta_vc.dat", "data/main.scm", "text/american.gxt",
                "audio/sfx.raw", "audio/sfx.sdt")
    missing = [name for name in required if not (dest / name).is_file()]
    if missing:
        raise ValueError("missing required game files: " + ", ".join(missing))
    adapt_lighting_maps(dest)


def adapt_lighting_maps(root):
    """Omit expanded lighting overlays when they exceed v9's timed-model pool."""
    configs = [root / "data/default.dat", root / "data/gta_vc.dat"]

    def time_models():
        count = 0
        for config in configs:
            if not config.is_file():
                continue
            for line in config.read_text(encoding="latin-1").splitlines():
                fields = line.split()
                if not fields or fields[0].upper() != "IDE":
                    continue
                path = root / fields[-1].replace("\\", "/").lower()
                section = ""
                for entry in path.read_text(encoding="latin-1").splitlines():
                    entry = entry.split("#", 1)[0].split("//", 1)[0].strip()
                    if not entry:
                        continue
                    if entry == "end":
                        section = ""
                    elif entry.isalpha():
                        section = entry.lower()
                    elif section == "tobj":
                        count += 1
        return count

    before = time_models()
    if before <= 385:
        return
    for config in configs:
        if not config.is_file():
            continue
        lines = config.read_text(encoding="latin-1").splitlines(keepends=True)
        kept = []
        for line in lines:
            fields = line.split()
            path = fields[-1].replace("\\", "/").lower() if fields else ""
            overlay = path.startswith(("data/maps/neons/", "data/maps/winlights/"))
            if fields and fields[0].upper() in ("IDE", "IPL", "COLFILE") and overlay:
                continue
            kept.append(line)
        if kept != lines:
            # Never write through a symlink into the read-only original install.
            config.unlink()
            config.write_text("".join(kept), encoding="latin-1")
    after = time_models()
    if after > 385:
        raise ValueError(f"install has {after} timed map models; revcDOS v9 supports 385. "
                         "Use an unmodified PC install.")
    print(f"prepare: omitted expanded neon/window-light overlays ({before} -> {after} "
          "timed models; engine limit 385)", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("dest", type=Path, nargs="?")
    args = parser.parse_args()
    try:
        install = find_install(args.root.resolve())
        if install is None:
            raise SystemExit(1)
        if args.dest:
            stage(install, args.dest)
        else:
            print(install)
    except ValueError as error:
        parser.exit(2, f"prepare: {error}\n")


if __name__ == "__main__":
    main()
