import importlib.util
import hashlib
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def image_module():
    return load_module("luca_image_under_test", ROOT / "game-tools" / "luca_image.py")


def test_cz0_round_trip_preserves_rgba_and_geometry(image_module):
    source = image_module.CzImage(
        version=3,
        width=2,
        height=2,
        bpp=32,
        pixels=bytes(range(16)),
        offset_x=-2,
        offset_y=3,
        canvas_width=8,
        canvas_height=9,
    )
    encoded = image_module.encode_cz0(source)
    decoded = image_module.decode_cz(encoded)
    assert decoded.version == 0
    assert decoded.width == source.width
    assert decoded.height == source.height
    assert decoded.bpp == source.bpp
    assert decoded.pixels == source.pixels
    assert decoded.offset_x == source.offset_x
    assert decoded.offset_y == source.offset_y
    assert decoded.canvas_width == source.canvas_width
    assert decoded.canvas_height == source.canvas_height


def test_cz0_rejects_trailing_or_truncated_payload(image_module):
    source = image_module.CzImage(version=0, width=1, height=1, bpp=32, pixels=b"\x01\x02\x03\x04")
    encoded = image_module.encode_cz0(source)
    with pytest.raises(ValueError, match="payload size mismatch"):
        image_module.decode_cz(encoded[:-1])
    with pytest.raises(ValueError, match="payload size mismatch"):
        image_module.decode_cz(encoded + b"\0")


def test_cz0_round_trip_preserves_indexed_palette(image_module):
    palette = bytes(value for index in range(256) for value in (index, 255 - index, index // 2, 255))
    source = image_module.CzImage(
        version=1,
        width=2,
        height=2,
        bpp=8,
        pixels=bytes((0, 1, 127, 255)),
        palette=palette,
    )
    decoded = image_module.decode_cz(image_module.encode_cz0(source))
    assert decoded.palette == palette
    assert decoded.pixels == source.pixels
    assert image_module.rgba_pixels(decoded) == bytes(
        (
            0, 255, 0, 255,
            1, 254, 0, 255,
            127, 128, 63, 255,
            255, 0, 127, 255,
        )
    )


def test_indexed_cz_requires_exact_palette(image_module):
    with pytest.raises(ValueError, match="require 256 RGBA colors"):
        image_module.CzImage(version=0, width=1, height=1, bpp=8, pixels=b"\0")


def test_cz0_round_trip_preserves_248_marker_palette(image_module):
    palette = bytes(value for index in range(256) for value in (index, 255 - index, index // 2, 255))
    source = image_module.CzImage(
        version=1,
        width=2,
        height=1,
        bpp=248,
        pixels=bytes((0, 200)),
        palette=palette,
    )
    decoded = image_module.decode_cz(image_module.encode_cz0(source))
    assert decoded.bpp == 248
    assert decoded.pixels == source.pixels
    assert decoded.palette == palette
    assert image_module.rgba_pixels(decoded) == bytes((0, 255, 0, 255, 200, 55, 100, 255))


def test_cz4_plane_delta_decode(image_module):
    raw = bytes((
        10, 20, 30,
        1, 2, 3,
        40, 50, 60,
        4, 5, 6,
        70, 80, 90,
        7, 8, 9,
        100, 1, 110, 2, 120, 3,
    ))
    decoded = image_module._decode_cz4_pixels(raw, width=1, height=6)
    assert decoded == bytes((
        10, 20, 30, 100,
        11, 22, 33, 101,
        40, 50, 60, 110,
        44, 55, 66, 112,
        70, 80, 90, 120,
        77, 88, 99, 123,
    ))


def test_real_cgm_select_cz4_rgba_hash(image_module):
    sys.path.insert(0, str(ROOT / "game-tools"))
    from luca import Pak

    path = ROOT / "build" / "steam" / "SYSCG.pristine.PAK"
    if not path.exists():
        pytest.skip("pristine SYSCG archive is not available")
    pak = Pak(path)
    entry = pak.entries[46]
    assert (entry.entry_id, entry.name) == (60047, "CGM_SELECTen")
    decoded = image_module.decode_cz(pak.read_entry(entry))
    assert decoded.version == 4
    assert (decoded.width, decoded.height, decoded.bpp) == (4152, 684, 32)
    assert hashlib.sha256(decoded.pixels).hexdigest() == "53108b5d09b97149ed4e0102573169e47aa9c8f4ccc5b23a29957d63d4cece61"


def test_cz_rejects_unknown_version(image_module):
    data = bytearray(64)
    data[:4] = b"CZ5\0"
    data[4:16] = (16).to_bytes(4, "little") + (1).to_bytes(2, "little") * 3 + (4).to_bytes(2, "little")
    with pytest.raises(ValueError, match="unsupported CZ version byte"):
        image_module.read_cz_metadata(bytes(data))
    with pytest.raises(ValueError, match="unsupported CZ version byte"):
        image_module.decode_cz(bytes(data))
