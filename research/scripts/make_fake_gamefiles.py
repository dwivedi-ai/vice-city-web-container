"""Build a tiny *synthetic* Vice City-shaped folder (no real game content)
to exercise the prepare pipeline: gta3.img/.dir, cuts.img/.dir, an .adf
radio station, sfx.raw/.sdt and a few plain data files."""
import os, struct, subprocess, sys
out = sys.argv[1]
def w(rel, data):
    p = os.path.join(out, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(data)
def img(base, names):
    blob, dirb = b"", b""
    for n in names:
        body = (n.encode() * 600)[:4096]
        dirb += struct.pack("<II24s", len(blob) // 2048, len(body) // 2048, n.encode())
        blob += body
    w(base + ".img", blob); w(base + ".dir", dirb)
img("models/GTA3", ["airport.col", "admiral.dff", "admiral.txd", "notpreloaded.dff"])
img("anim/CUTS", ["int_a.dat", "ass_1.ifp"])
w("data/gta_vc.dat", b"IDE DATA\\DEFAULT.IDE\n" * 50)
w("data/handling.cfg", b"; fake handling\n" * 200)
w("models/hud.txd", os.urandom(512) * 8)
w("gta-vc.exe", b"MZ fake")
w("movies/logo.mpg", b"fake")
tmp = os.path.join(out, "_tone.mp3")
subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=2", "-ac", "2", tmp], check=True)
mp3 = open(tmp, "rb").read(); os.remove(tmp)
w("Audio/FLASH.ADF", bytes(b ^ 0x22 for b in mp3))
w("Audio/ass_1.wav", b"")  # placeholder replaced below
subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=1", os.path.join(out, "Audio/ass_1.wav")], check=True)
pcm1 = b"".join(struct.pack("<h", (i * 300) % 30000) for i in range(22050))
pcm2 = b"".join(struct.pack("<h", (i * 700) % 30000) for i in range(11025))
w("Audio/sfx.RAW", pcm1 + pcm2)
w("Audio/sfx.SDT", struct.pack("<IIIIi", 0, len(pcm1), 22050, 0, -1) + struct.pack("<IIIIi", len(pcm1), len(pcm2), 32000, 0, -1))
print("fake gamefiles in", out)
