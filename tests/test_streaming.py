import io
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'standalone'))
try:
    from PIL import Image
    from streaming import children, chunk, dds, encode_dxt, reduce_txd
except ImportError:
    Image = None


@unittest.skipIf(Image is None, 'Pillow 11.3+ is required for texture tests')
class TextureTests(unittest.TestCase):
    def fixture(self, compression=1, alpha=0, size=128):
        im = Image.new('RGBA' if compression == 3 else 'RGB', (size, size), (120, 80, 30, 136) if compression == 3 else (120, 80, 30))
        data = bytearray(88)
        struct.pack_into('<I', data, 0, 8)
        struct.pack_into('<IIHHBBBB', data, 72, 0x300 if compression == 3 else 0x200, alpha, size, size, 16, 1, 4, compression)
        pixels = encode_dxt(im, compression)
        native = chunk(1, 1, bytes(data) + struct.pack('<I', len(pixels)) + pixels) + chunk(3, 1, b'')
        return chunk(0x16, 1, chunk(1, 1, struct.pack('<HH', 1, 0)) + chunk(0x15, 1, native)) + bytes(37)

    def native(self, blob):
        children_ = list(children(blob, 12, 12 + struct.unpack_from('<I', blob, 4)[0]))
        return list(children(children_[1][2]))[0][2]

    def test_opaque_texture_reduces_resolution_preserving_archive_length(self):
        original = self.fixture()
        low = reduce_txd(original, 64)
        self.assertEqual(len(original), len(low))
        native = self.native(low)
        self.assertEqual(struct.unpack_from('<HH', native, 80), (64, 64))
        size = struct.unpack_from('<I', native, 88)[0]
        decoded = Image.open(io.BytesIO(dds(native[92:92+size], 64, 64, 1)))
        self.assertLess(abs(decoded.getpixel((20, 20))[0]-120), 12)
        self.assertLess(size, struct.unpack_from('<I', self.native(original), 88)[0])

    def test_dxt3_alpha_survives_reduction(self):
        native = self.native(reduce_txd(self.fixture(3, 1), 64))
        size = struct.unpack_from('<I', native, 88)[0]
        decoded = Image.open(io.BytesIO(dds(native[92:92+size], 64, 64, 3)))
        self.assertEqual(decoded.getpixel((0, 0))[3], 136)
        self.assertEqual(decoded.getpixel((19, 24))[3], 136)

    def test_cutout_alpha_stays_at_original_resolution(self):
        original = self.fixture(1, 1)
        self.assertEqual(self.native(reduce_txd(original)), self.native(original))

    def test_palette_loading_artwork_preserves_palette(self):
        header = bytearray(88)
        struct.pack_into('<I', header, 0, 8)
        struct.pack_into('<IIHHBBBB', header, 72, 0x2600, 0, 128, 128, 8, 1, 4, 0)
        palette = bytes(range(256)) * 4
        pixels = bytes([23]) * 128 * 128
        native = chunk(1, 1, header + palette + struct.pack('<I', len(pixels)) + pixels)
        original = chunk(0x16, 1, chunk(1, 1, struct.pack('<HH', 1, 0)) + chunk(0x15, 1, native))
        data = self.native(reduce_txd(original, 64))
        self.assertEqual(data[88:1112], palette)
        self.assertEqual(struct.unpack_from('<HH', data, 80), (64, 64))
        self.assertEqual(data[1116:], bytes([23])*4096)

    def test_malformed_dictionary_is_rejected(self):
        with self.assertRaises(ValueError):
            reduce_txd(struct.pack('<III', 0x16, 1000, 1))


if __name__ == '__main__':
    unittest.main()
