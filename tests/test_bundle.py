import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BundleTests(unittest.TestCase):
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
