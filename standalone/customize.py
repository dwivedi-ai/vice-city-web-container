"""Apply the minimal, local-save-only shell to the pinned v9 distribution.

Fail closed when upstream anchors change. The WASM edit touches only the menu
footer's data bytes, preserving every section size and memory address.
"""

import argparse
import hashlib
import re
import struct
from pathlib import Path

WASM_SHA256 = "bb59306a304de0560fab42bf96adc439dce763e06fcda8c63f8556060127bbc7"
# The last character's zero bytes are omitted at the end of this WASM data
# segment (linear memory starts zeroed). Do not overwrite the following segment.
FOOTER = "dos.zone/revcdos\n© DOS Zone Team, 2025".encode("utf-32le")[:-3]
BLANK_FOOTER = (" " * ((len(FOOTER) + 3) // 4)).encode("utf-32le")[:-3]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one upstream anchor: {old[:80]!r}")
    return text.replace(old, new, 1)


def erase_footer(blob):
    if blob.count(FOOTER) != 1:
        raise ValueError("Expected exactly one v9 menu footer")
    # The renderer retains the literal length: NULs would draw missing-glyph
    # boxes. Spaces render invisibly without changing the compiled layout.
    return blob.replace(FOOTER, BLANK_FOOTER, 1)


def chunks(blob, start, end):
    pos = start
    while pos < end:
        if pos + 12 > end:
            raise ValueError("Truncated RenderWare chunk")
        kind, size, version = struct.unpack_from("<III", blob, pos)
        stop = pos + 12 + size
        if stop > end:
            raise ValueError("RenderWare chunk exceeds its container")
        yield kind, version, blob[pos:stop]
        pos = stop


def texture_name(chunk):
    # Native texture -> struct -> platform/filter flags -> 32-byte name.
    if len(chunk) < 64 or struct.unpack_from("<I", chunk, 12)[0] != 1:
        raise ValueError("Invalid native texture")
    return chunk[32:64].split(b"\0", 1)[0]


def restore_logo(current, original):
    def contents(blob):
        top = list(chunks(blob, 0, len(blob)))
        if len(top) != 1 or top[0][0] != 0x16:
            raise ValueError("Expected one texture dictionary")
        return top[0][1], list(chunks(blob, 12, len(blob)))

    version, target = contents(current)
    _, source = contents(original)
    logos = [raw for kind, _, raw in source if kind == 0x15 and texture_name(raw) == b"vc_logo"]
    if len(logos) != 1:
        raise ValueError("Original game must contain exactly one vc_logo texture")
    count = 0
    out = []
    for kind, _, raw in target:
        if kind == 0x15 and texture_name(raw) == b"vc_logo":
            raw = logos[0]
            count += 1
        out.append(raw)
    if count != 1:
        raise ValueError("Prepared game must contain exactly one vc_logo texture")
    payload = b"".join(out)
    return struct.pack("<III", 0x16, len(payload), version) + payload


def customize_engine(root, templates):
    wasm = root / "index.wasm"
    blob = wasm.read_bytes()
    if hashlib.sha256(blob).hexdigest() != WASM_SHA256:
        raise ValueError("Unexpected WASM build; review the footer patch before updating")
    wasm.write_bytes(erase_footer(blob))

    html = (root / "index.html").read_text()
    touch_css = html.split("        .touch-controls-wrapper {", 1)[1].split(
        "        video::-webkit-media-controls {", 1)[0]
    touch_css = ".touch-controls-wrapper {" + touch_css
    body = re.search(r"<body\b[^>]*>", html).group(0)
    controls = html.split('    <div class="touch-controls-wrapper">', 1)[1].split(
        "    <script", 1)[0]
    controls = '<div class="touch-controls-wrapper">' + controls
    shell = (templates / "engine-shell.html").read_text()
    for marker, value in [("{{TOUCH_CSS}}", touch_css), ("{{BODY}}", body),
                          ("{{TOUCH_CONTROLS}}", controls)]:
        shell = replace_once(shell, marker, value)
    (root / "index.html").write_text(shell)

    game = (root / "game.js").read_text()
    # Keep the proven module/filesystem/input setup and original settings.
    # Omit the upstream landing page, cloud hooks, and key-resolution code.
    core = "async function loadGame() {" + game.split("async function loadGame() {", 1)[1].split(
        "const clickToPlay =", 1)[0]
    core = replace_once(core, "                Module['_async_main']();", """                try {
                    Module['_async_main']();
                } catch (error) {
                    // Emscripten unwinds the native main loop to yield to JS.
                    if (error !== 'unwind') throw error;
                }
                document.querySelector('.start-container').hidden = true;
                window.top.postMessage({ event: 'game.started' }, location.origin);""")
    core = replace_once(core, "                console.error('mainCalled error:', e);",
                        "                failGame(e);")
    start = core.index("        hotelMission: () => {")
    end = core.index("\n        },", start) + len("\n        },")
    core = core[:start] + "        hotelMission: () => {},\n        onAbort: failGame," + core[end:]
    core = replace_once(core, "fetch(wasm_content ? wasm_content : \"index.wasm\")", 'fetch("index.wasm")')
    settings = "const revc_iniDefault =" + game.split("const revc_iniDefault =", 1)[1]
    runtime = (templates / "engine-launcher.js").read_text()
    (root / "game.js").write_text(runtime + "\n" + core + "\n" + settings)

    # Without the optional IDBFS wrapper, index.js uses native IndexedDB sync.
    # Remove the integration entirely, including any old compressed copies.
    for name in ("jsdos-cloud-sdk.js", "idbfs.js", "host.html", "revcdos.jpg", "wasted.png"):
        for suffix in ("", ".gz", ".br", ".zst"):
            (root / (name + suffix)).unlink(missing_ok=True)
    for path in root.iterdir():
        if path.suffix in (".gz", ".br", ".zst"):
            path.unlink()
    print("Customized v9 launcher, original local saves, and menu footer")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    engine = sub.add_parser("engine")
    engine.add_argument("root", type=Path)
    engine.add_argument("templates", type=Path)
    logo = sub.add_parser("logo")
    logo.add_argument("root", type=Path)
    logo.add_argument("install", type=Path)
    args = parser.parse_args()
    if args.action == "engine":
        customize_engine(args.root, args.templates)
    else:
        sources = [p for p in args.install.rglob("*")
                   if p.is_file() and p.name.lower() == "fronten1.txd" and p.parent.name.lower() == "models"]
        if len(sources) != 1:
            raise ValueError("Expected exactly one original models/fronten1.txd")
        target = args.root / "vc-assets/local/models/fronten1.txd"
        target.write_bytes(restore_logo(target.read_bytes(), sources[0].read_bytes()))
        print("Restored original Vice City logo from", sources[0])


if __name__ == "__main__":
    main()
