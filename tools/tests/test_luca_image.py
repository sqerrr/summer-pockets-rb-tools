import importlib.util
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


def test_cz_rejects_unknown_version(image_module):
    with pytest.raises(ValueError, match="unsupported CZ version"):
        image_module.decode_cz(b"CZ4\0" + b"\0" * 64)
