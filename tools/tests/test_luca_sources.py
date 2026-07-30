import importlib.util
import struct
from pathlib import Path


def load_luca():
    path = Path(__file__).parents[2] / "game-tools" / "luca.py"
    spec = importlib.util.spec_from_file_location("luca_sources", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def record(luca, opcode, flag, fixed_params, params):
    length = 4 + 2 * len(fixed_params) + len(params)
    return luca.ScriptRecord(
        offset=100,
        length=length,
        opcode=opcode,
        name=f"OP_{opcode}",
        flag=flag,
        fixed_params=tuple(fixed_params),
        params=params,
    )


def test_opcode36_multilingual_layout():
    luca = load_luca()
    params = (
        b"\x01\x02"
        + luca.encode_luca_string("日本語", "utf-16le")
        + luca.encode_luca_string("English", "utf-8")
        + luca.encode_luca_string("简体中文", "utf-16le")
        + b"\x0b"
    )
    result = luca.classify_source_record(record(luca, 36, 3, (1, 2), params))
    assert result.classification == "translatable"
    assert tuple(item.encoding for item in result.strings) == (
        "utf-16le", "utf-8", "utf-16le"
    )


def test_opcode40_multilingual_layout():
    luca = load_luca()
    params = (
        b"\0" * 8
        + luca.encode_luca_string("日", "utf-16le")
        + luca.encode_luca_string("E", "utf-16le")
        + luca.encode_luca_string("中", "utf-16le")
        + b"\0\0\x02\0"
    )
    result = luca.classify_source_record(record(luca, 40, 1, (1,), params))
    assert result.classification == "translatable"


def test_service_layout_is_not_text():
    luca = load_luca()
    params = b"\0" * 8 + b"\x0b" + struct.pack("<I", 123)
    result = luca.classify_source_record(record(luca, 36, 3, (1, 2), params))
    assert result.classification == "service_nontext"


def test_unknown_candidate_fails_closed():
    luca = load_luca()
    result = luca.classify_source_record(record(luca, 36, 0, (), b"bad"))
    assert result.classification == "unknown_candidate"


def test_source_id_does_not_use_offsets_or_text():
    luca = load_luca()
    assert luca.make_source_id(7, 42) == "SRC_LUCA_E000007_R000042_G00"
