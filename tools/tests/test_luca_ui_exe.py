import copy
import hashlib
import importlib.util
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
GAME_TOOLS = ROOT / "game-tools"


def load_module(name, path):
    sys.path.insert(0, str(GAME_TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ui_exe_module():
    return load_module("luca_ui_exe_under_test", GAME_TOOLS / "build_luca_ui_exe.py")


def _canonical_config(module, entries):
    return {
        "schema_version": 1,
        "asset_id": "runtime_ui_strings",
        "status": "draft",
        "target": {
            "profile": "steam_luca",
            "file": "SummerPocketsRB.exe",
            "packed_sha256": "sha256:" + module.PACKED_SHA256,
            "steamless_unpacked_sha256": "sha256:" + module.UNPACKED_SHA256,
            "language_slot": "english",
        },
        "entry_count": len(entries),
        "entries": entries,
    }


def _entry(offset, source, replacement, scope="options", category="dialog"):
    return {
        "file_offset": offset,
        "file_offset_hex": f"0x{offset:X}",
        "text_en": source,
        "text_ru": replacement,
        "category": category,
        "status": "draft",
        "build_scope": scope,
    }


def test_canonical_validation_checks_source_offsets_and_token_order(ui_exe_module):
    entries = [
        _entry(4, "$A1Delete No. %02d?$d", "$A1Удалить № %02d?$d"),
        _entry(40, "Same %s", "Same %s", "core"),
    ]
    config = _canonical_config(ui_exe_module, entries)
    source = bytearray(64)
    source[4:4 + len(b"$A1Delete No. %02d?$d\0")] = b"$A1Delete No. %02d?$d\0"
    source[40:40 + len(b"Same %s\0")] = b"Same %s\0"

    validation = ui_exe_module.validate_canonical(config, bytes(source))
    assert validation == {
        "entry_count": 2,
        "scope_counts": {"core": 1, "options": 1, "later": 0},
    }
    assert ui_exe_module.protected_tokens(entries[0]["text_en"]) == ("$A1", "%02d", "$d")
    assert ui_exe_module.protected_tokens("Volume 66%") == ()

    damaged_tokens = copy.deepcopy(config)
    damaged_tokens["entries"][0]["text_ru"] = "$A1Удалить?$d %02d"
    with pytest.raises(ValueError, match="protected token sequence changed"):
        ui_exe_module.validate_canonical(damaged_tokens, bytes(source))

    duplicate = copy.deepcopy(config)
    duplicate["entries"][1]["file_offset"] = 4
    duplicate["entries"][1]["file_offset_hex"] = "0x4"
    with pytest.raises(ValueError, match="duplicate canonical file offset"):
        ui_exe_module.validate_canonical(duplicate, bytes(source))

    changed_source = bytearray(source)
    changed_source[4] = ord("X")
    with pytest.raises(ValueError, match="source English bytes differ"):
        ui_exe_module.validate_canonical(config, bytes(changed_source))


def test_canonical_validation_accepts_utf8_and_rejects_interior_suffixes(ui_exe_module):
    source_text = "Positioned at ❝Yes❞"
    entry = _entry(8, source_text, "На ❝Да❞")
    config = _canonical_config(ui_exe_module, [entry])
    source = bytearray(80)
    encoded = source_text.encode("utf-8") + b"\0"
    source[8:8 + len(encoded)] = encoded
    ui_exe_module.validate_canonical(config, bytes(source))

    suffix = _canonical_config(ui_exe_module, [_entry(12, "tioned at ❝Yes❞", "На ❝Да❞")])
    with pytest.raises(ValueError, match="starts inside a NUL field"):
        ui_exe_module.validate_canonical(suffix, bytes(source))


def test_scope_selection_skips_only_exact_no_ops(ui_exe_module):
    config = _canonical_config(ui_exe_module, [
        _entry(1, "Options", "Настройки", "options"),
        _entry(2, "%s %d", "%s %d", "options"),
        _entry(3, "Core", "Основа", "core"),
        _entry(4, "Later", "Позже", "later"),
        _entry(5, "Track", "Трек", "later", "music_title"),
        _entry(6, "Jul.", "июл.", "later", "date_label"),
    ])

    options = ui_exe_module.select_scope_rows(config, "options")
    assert [row["file_offset"] for row in options] == [1, 2]
    assert [row["file_offset"] for row in ui_exe_module.semantic_rows(options)] == [1]
    assert [row["file_offset"] for row in ui_exe_module.select_scope_rows(config, "core")] == [3]
    assert [row["file_offset"] for row in ui_exe_module.select_scope_rows(config, "first_wave")] == [1, 2, 3]
    assert [row["file_offset"] for row in ui_exe_module.select_scope_rows(config, "interface")] == [1, 2, 3, 4]
    assert [row["file_offset"] for row in ui_exe_module.select_scope_rows(config, "all")] == [1, 2, 3, 4, 5, 6]


def test_alignment_payload_and_section_placement_helpers(ui_exe_module):
    placement = ui_exe_module.derive_section_placement(
        source_size=0x1234,
        file_alignment=0x200,
        section_alignment=0x1000,
        size_of_headers=0x600,
        section_table_offset=0x200,
        number_of_sections=3,
        sections=(
            ui_exe_module.SectionExtent(0x1000, 0x610, 0x800),
            ui_exe_module.SectionExtent(0x2000, 0x111, 0x200),
        ),
        payload_size=0x211,
    )
    assert placement.header_offset == 0x278
    assert placement.raw_offset == 0x1400
    assert placement.raw_size == 0x400
    assert placement.rva == 0x3000
    assert placement.virtual_size == 0x211
    assert placement.size_of_image == 0x4000

    targets = (
        ui_exe_module.StringTarget(0x10, "A", "Да", "options", "button", 0x110, 0x140000110),
        ui_exe_module.StringTarget(0x20, "B", "Закрыть", "options", "button", 0x120, 0x140000120),
    )
    payload, locations = ui_exe_module.build_string_payload(
        targets,
        section_rva=0x5000,
        section_raw_offset=0x1800,
        image_base=0x140000000,
    )
    assert locations[0x10].payload_offset == 0
    assert locations[0x20].payload_offset % 8 == 0
    assert locations[0x10].raw_offset == 0x1800
    assert locations[0x20].rva == 0x5000 + locations[0x20].payload_offset
    assert payload[locations[0x10].payload_offset:].startswith("Да".encode("utf-8") + b"\0")
    assert payload[locations[0x20].payload_offset:].startswith("Закрыть".encode("utf-8") + b"\0")


def test_pointer_cells_require_dir64_relocation(ui_exe_module):
    image_base = 0x140000000
    old_va = image_base + 0x1234
    data = bytearray(0x80)
    struct.pack_into("<Q", data, 0x10, old_va)
    struct.pack_into("<Q", data, 0x28, old_va)
    sections = (
        ui_exe_module.SectionView(".rdata", 0x2000, 0, 0x80, False),
    )
    pointers, unsupported = ui_exe_module.classify_pointer_cells(
        bytes(data),
        sections,
        {0x2010},
        {old_va: 0x500},
    )
    assert pointers == (ui_exe_module.PointerReference(0x500, 0x2010, 0x10),)
    assert len(unsupported) == 1
    assert unsupported[0].kind == "absolute_qword_without_dir64_relocation"
    assert unsupported[0].rva == 0x2028

    fake_pe = SimpleNamespace(DIRECTORY_ENTRY_BASERELOC=(
        SimpleNamespace(entries=(
            SimpleNamespace(type=ui_exe_module.DIR64, rva=0x2010),
            SimpleNamespace(type=3, rva=0x2020),
        )),
    ))
    assert ui_exe_module.collect_dir64_relocations(fake_pe) == {0x2010}


def test_zero_reference_exceptions_are_exact_and_fail_closed(ui_exe_module, monkeypatch):
    known_offset = 0x7777
    known_source = "Known zero-ref string"
    monkeypatch.setattr(ui_exe_module, "KNOWN_ZERO_REFERENCE_STRINGS", {known_offset: known_source})
    known = ui_exe_module.StringTarget(
        known_offset,
        known_source,
        "Русский текст",
        "options",
        "options_help",
        0x1000,
        0x140001000,
    )
    active = ui_exe_module.StringTarget(
        0x1234,
        "Active",
        "Активно",
        "options",
        "options_label",
        0x2000,
        0x140002000,
    )
    retained, exceptions = ui_exe_module.partition_zero_reference_targets(
        (known, active),
        {known.source_file_offset: 0, active.source_file_offset: 1},
    )
    assert retained == (active,)
    assert exceptions[0].target == known
    assert "zero supported refs" in exceptions[0].evidence

    unknown = ui_exe_module.StringTarget(
        0x9999,
        "Unknown",
        "Неизвестно",
        "options",
        "options_label",
        0x3000,
        0x140003000,
    )
    with pytest.raises(ValueError, match="zero supported references: 0x9999"):
        ui_exe_module.partition_zero_reference_targets(
            (active, unknown),
            {active.source_file_offset: 1, unknown.source_file_offset: 0},
        )


def test_backup_selection_prefers_existing_verified_backup(ui_exe_module, tmp_path):
    pristine = b"packed-pristine-exe"
    expected = hashlib.sha256(pristine).hexdigest()
    installed = tmp_path / "installed.exe"
    backup = tmp_path / "backup.exe"
    installed.write_bytes(pristine)

    selected = ui_exe_module.select_packed_source(
        require_backup=True,
        installed=installed,
        backup=backup,
        expected_hash=expected,
    )
    assert selected == backup
    assert backup.read_bytes() == pristine

    installed.write_bytes(b"currently-installed-russian-artifact")
    selected = ui_exe_module.select_packed_source(
        require_backup=False,
        installed=installed,
        backup=backup,
        expected_hash=expected,
    )
    assert selected == backup
    assert backup.read_bytes() == pristine


def test_install_and_restore_refuse_while_game_is_running(ui_exe_module, monkeypatch, tmp_path):
    monkeypatch.setattr(ui_exe_module, "game_is_running", lambda: True)
    installed = tmp_path / "installed.exe"
    backup = tmp_path / "backup.exe"
    artifact = tmp_path / "artifact.exe"
    installed.write_bytes(b"installed")
    backup.write_bytes(b"backup")
    artifact.write_bytes(b"artifact")

    with pytest.raises(SystemExit, match="game is running"):
        ui_exe_module.install_artifact(artifact, installed, backup)
    with pytest.raises(SystemExit, match="game is running"):
        ui_exe_module.restore_installed(installed, backup)
    assert installed.read_bytes() == b"installed"
