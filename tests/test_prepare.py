"""Regression checks using synthetic game files; no game install is required."""

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stage_game", ROOT / "docker/prepare/stage_game.py")
stage_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage_game)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-prepare-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / "GTA Vice City"
        for name in ("Models/GTA3.IMG", "Models/GTA3.DIR", "Anim/PED.IFP",
                     "Data/MAIN.SCM", "TEXT/AMERICAN.GXT", "Audio/TEST.WAV",
                     "Sound/sfx.RAW", "Sound/sfx.SDT", "Radio/FLASH.adf",
                     "plugins/ignored.asi"):
            self.write(name, "test data")
        self.write("Data/GTA_VC.DAT", "# game maps\n")

    def write(self, name, content):
        path = self.install / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_nested_install_and_split_audio_preserve_originals(self):
        self.assertEqual(stage_game.find_install(self.root), self.install)
        self.assertEqual(stage_game.find_install(self.install), self.install)
        dest = self.root / "prepared"
        stage_game.stage(self.install, dest)
        self.assertTrue((dest / "models/gta3.dir").is_symlink())
        self.assertEqual((dest / "audio/flash.adf").read_text(), "test data")
        self.assertTrue((dest / "audio/sfx.raw").is_symlink())
        self.assertFalse((dest / "plugins").exists())
        self.assertTrue((self.install / "Radio/FLASH.adf").is_file())

    def test_ambiguous_installs_are_rejected(self):
        shutil.copytree(self.install, self.root / "Other install")
        with self.assertRaisesRegex(ValueError, "multiple game installs"):
            stage_game.find_install(self.root)

    def test_conflicting_audio_is_rejected(self):
        self.write("Audio/flash.adf", "different station")
        with self.assertRaisesRegex(ValueError, "conflicting game files"):
            stage_game.stage(self.install, self.root / "prepared")

    def test_missing_required_data_is_rejected(self):
        (self.install / "Models/GTA3.DIR").unlink()
        with self.assertRaisesRegex(ValueError, "models/gta3.dir"):
            stage_game.stage(self.install, self.root / "prepared")

    def test_expanded_lighting_is_disabled_only_in_prepared_copy(self):
        config = ("IDE DATA\\MAPS\\base.ide\n"
                  "IDE DATA\\MAPS\\neons\\neons.ide\n"
                  "IPL DATA\\MAPS\\neons\\neons.ipl\n"
                  "COLFILE 0 DATA\\MAPS\\neons\\neons.col\n")
        self.write("Data/GTA_VC.DAT", config)
        self.write("Data/maps/base.ide", "tobj\n" + "1, model\n" * 343 + "end\n")
        self.write("Data/maps/neons/neons.ide", "tobj\n" + "2, light\n" * 126 + "end\n")
        dest = self.root / "prepared"
        stage_game.stage(self.install, dest)
        self.assertEqual((self.install / "Data/GTA_VC.DAT").read_text(), config)
        self.assertNotIn("neons", (dest / "data/gta_vc.dat").read_text())
        self.assertIn("base.ide", (dest / "data/gta_vc.dat").read_text())

    def test_unsupported_model_overflow_is_rejected(self):
        self.write("Data/GTA_VC.DAT", "IDE DATA\\MAPS\\base.ide\n")
        self.write("Data/maps/base.ide", "tobj\n" + "1, model\n" * 386 + "end\n")
        with self.assertRaisesRegex(ValueError, "supports 385"):
            stage_game.stage(self.install, self.root / "prepared")


if __name__ == "__main__":
    unittest.main()
