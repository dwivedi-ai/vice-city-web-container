import importlib.util
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("customize", ROOT / "standalone/customize.py")
customize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(customize)


def chunk(kind, payload):
    return struct.pack("<III", kind, len(payload), 0x1803FFFF) + payload


def texture(name, payload):
    return chunk(0x15, chunk(1, bytes(8) + name.ljust(32, b"\0") + payload) + chunk(3, b""))


def dictionary(*textures):
    return chunk(0x16, chunk(1, struct.pack("<I", len(textures))) + b"".join(textures) + chunk(3, b""))


class CustomizeTests(unittest.TestCase):
    def test_footer_preserves_following_segment_and_binary_size(self):
        prefix = b"\0asm\x01\0\0\0before"
        following_segment = b"\0A\xcc\xcb\x1f\x0b\xea"
        original = prefix + customize.FOOTER + following_segment
        result = customize.erase_footer(original)
        self.assertEqual(len(result), len(original))
        self.assertEqual(result, prefix + customize.BLANK_FOOTER + following_segment)
        self.assertEqual(customize.BLANK_FOOTER[::4], b" " * 38)

    def test_unknown_or_duplicate_footer_is_rejected(self):
        for blob in (b"new engine", customize.FOOTER * 2):
            with self.assertRaises(ValueError):
                customize.erase_footer(blob)

    def test_only_logo_is_replaced_even_when_size_changes(self):
        mouse = texture(b"mouse", b"unchanged mouse")
        background = texture(b"background", b"unchanged background")
        original_logo = texture(b"vc_logo", b"original game art" * 20)
        source = dictionary(texture(b"mouse", b"other mouse"), original_logo)
        prepared = dictionary(mouse, texture(b"vc_logo", b"branded"), background)
        result = customize.restore_logo(prepared, source)
        self.assertEqual(result, dictionary(mouse, original_logo, background))

    def test_missing_logo_and_malformed_chunks_are_rejected(self):
        valid = dictionary(texture(b"vc_logo", b"logo"))
        for source in (dictionary(texture(b"mouse", b"mouse")), valid[:-1]):
            with self.assertRaises(ValueError):
                customize.restore_logo(valid, source)


if __name__ == "__main__":
    unittest.main()
