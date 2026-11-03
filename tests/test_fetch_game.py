"""Archive extraction regressions; fixtures contain no game assets."""

import importlib.util
import io
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fetch_game', ROOT / 'docker/prepare/fetch_game.py')
fetch_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_game)


class ExtractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='.test-extract-', dir=ROOT)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dest = self.root / 'out'
        self.dest.mkdir()

    def archive(self, format, names):
        archive = self.root / ('backup.' + format)
        if format == 'zip':
            with zipfile.ZipFile(archive, 'w') as z:
                for name in names:
                    z.writestr(name, b'fixture')
        else:
            with tarfile.open(archive, 'w') as t:
                for name in names:
                    member = tarfile.TarInfo(name)
                    member.size = 7
                    t.addfile(member, io.BytesIO(b'fixture'))
        return archive

    def test_nested_files_extract_in_both_formats(self):
        for format in ('zip', 'tar'):
            with self.subTest(format=format):
                fetch_game.extract(self.archive(format, ['Game/models/example.dat']), self.dest)
                self.assertEqual((self.dest / 'Game/models/example.dat').read_bytes(), b'fixture')

    def test_escaping_and_absolute_paths_rejected_before_any_writes(self):
        for format in ('zip', 'tar'):
            for name in ('../out-sibling/escape', '../escape', str(self.root / 'absolute')):
                with self.subTest(format=format, name=name):
                    archive = self.archive(format, ['valid.dat', name])
                    with self.assertRaisesRegex(SystemExit, 'unsafe path'):
                        fetch_game.extract(archive, self.dest)
                    self.assertEqual(list(self.dest.iterdir()), [])
                    self.assertFalse((self.root / 'out-sibling').exists())
                    self.assertFalse((self.root / 'escape').exists())
                    self.assertFalse((self.root / 'absolute').exists())

    def test_tar_fallback_also_rejects_sibling_prefix_escape(self):
        archive = self.archive('tar', ['../out-sibling/escape'])
        # Emulate the old unfiltered default as well as the missing API;
        # modern Python otherwise tries to call the mocked data_filter itself.
        with patch.object(tarfile, 'data_filter', None, create=True), patch.object(
                tarfile.TarFile, 'extraction_filter', staticmethod(lambda member, path: member), create=True):
            with self.assertRaisesRegex(SystemExit, 'unsafe path'):
                fetch_game.extract(archive, self.dest)
            fetch_game.extract(self.archive('tar', ['Game/models/example.dat']), self.dest)
        self.assertFalse((self.root / 'out-sibling').exists())
        self.assertEqual((self.dest / 'Game/models/example.dat').read_bytes(), b'fixture')

    def test_tar_links_and_special_files_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind):
                archive = self.root / 'special.tar'
                with tarfile.open(archive, 'w') as t:
                    member = tarfile.TarInfo('special')
                    member.type = kind
                    member.linkname = '../out-sibling'
                    t.addfile(member)
                with self.assertRaisesRegex(SystemExit, 'unsafe entry'):
                    fetch_game.extract(archive, self.dest)
                self.assertEqual(list(self.dest.iterdir()), [])

    def test_zip_symlink_rejected(self):
        archive = self.root / 'link.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            member = zipfile.ZipInfo('link')
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(member, '../out-sibling')
        with self.assertRaisesRegex(SystemExit, 'special entry'):
            fetch_game.extract(archive, self.dest)

    def test_existing_destination_symlink_cannot_escape(self):
        outside = self.root / 'out-sibling'
        outside.mkdir()
        (self.dest / 'linked').symlink_to(outside, target_is_directory=True)
        for format in ('zip', 'tar'):
            with self.subTest(format=format):
                with self.assertRaisesRegex(SystemExit, 'unsafe path'):
                    fetch_game.extract(self.archive(format, ['linked/escape']), self.dest)
                self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
