import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BundleTests(unittest.TestCase):
    def test_radio_is_deferred_chunks_are_verified_and_streamed_changes_invalidate_urls(self):
        with tempfile.TemporaryDirectory(prefix=".test-bundle-", dir=ROOT) as tmp:
            data = Path(tmp)
            assets = {
                "vc-assets/local/models/boot.txd": b"a" * 10,
                "vc-assets/local/audio/flash.adf": b"radio" * 10,
                "vc-assets/local/models/later.dff": b"model",
            }
            for name, payload in assets.items():
                p = data / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(payload)
            preload = data / "preload.list"
            preload.write_text("vc-assets/local/models/boot.txd\nvc-assets/local/audio/flash.adf\n")
            command = [sys.executable, str(ROOT / "docker/prepare/bundle.py"), str(data),
                       "--preload-list", str(preload), "--compression", "none", "--part-size", "4"]
            subprocess.run(command, check=True, capture_output=True)
            manifest = json.loads((data / "bundle/manifest.json").read_text())
            self.assertEqual(manifest["preload"]["size"], 10)
            self.assertIn("vc-assets/local/audio/flash.adf", manifest["files"])
            self.assertEqual([p["size"] for p in manifest["preload"]["parts"]], [4, 4, 2])
            for part in manifest["preload"]["parts"]:
                payload = (data / part["url"]).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), part["sha256"])
                self.assertIn(part["sha256"], part["url"])
            (data / "vc-assets/local/models/later.dff").write_bytes(b"changed model")
            subprocess.run(command, check=True, capture_output=True)
            updated = json.loads((data / "bundle/manifest.json").read_text())
            self.assertNotEqual(manifest["version"], updated["version"])
            self.assertEqual(manifest["preload"]["parts"], updated["preload"]["parts"])
            subprocess.run([sys.executable, str(ROOT / "standalone/validate_data.py"), str(data)],
                           check=True, capture_output=True)
            (data / updated["preload"]["parts"][0]["url"]).write_bytes(b"bad!")
            result = subprocess.run([sys.executable, str(ROOT / "standalone/validate_data.py"), str(data)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Corrupt boot part", result.stderr)

    def test_install_map_files_are_included_and_bundle_is_valid(self):
        with tempfile.TemporaryDirectory(prefix=".test-bundle-", dir=ROOT) as tmp:
            data = Path(tmp)
            assets = {
                "vc-assets/local/models/boot.txd": b"texture" * 200,
                "vc-assets/local/data/maps/extra.ipl": b"inst\nend\n",
                "vc-assets/local/models/extra.col": b"COLL" + bytes(20),
                "vc-assets/local/models/later.dff": b"streamed model",
            }
            for name, payload in assets.items():
                p = data / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(payload)
            preload = data / "preload.list"
            preload.write_text("vc-assets/local/models/boot.txd\n")
            subprocess.run([sys.executable, str(ROOT / "docker/prepare/bundle.py"),
                            str(data), "--preload-list", str(preload),
                            "--compression", "none"], check=True, capture_output=True)
            manifest = json.loads((data / "bundle/manifest.json").read_text())
            boot = {entry[0] for entry in manifest["preload"]["files"]}
            self.assertIn("vc-assets/local/data/maps/extra.ipl", boot)
            self.assertIn("vc-assets/local/models/extra.col", boot)
            self.assertNotIn("vc-assets/local/models/later.dff", boot)
            self.assertFalse(list(data.rglob("*.br")))
            subprocess.run([sys.executable, str(ROOT / "standalone/validate_data.py"),
                            str(data)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
