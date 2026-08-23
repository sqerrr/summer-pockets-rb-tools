import importlib.util
from pathlib import Path
import struct
import sys

from PIL import Image, ImageFont
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
def ui_module():
    return load_module("luca_ui_images_under_test", GAME_TOOLS / "build_luca_ui_images.py")


def test_fit_and_condense_preserves_height_and_scales_only_when_needed(ui_module):
    font = ImageFont.truetype(str(ui_module.FONT_PATH), 52)
    natural = ui_module.fit_and_condense(
        "НАСТРОЙКИ",
        font,
        1000,
        fill=(255, 255, 255, 255),
    )
    condensed = ui_module.fit_and_condense(
        "НАСТРОЙКИ",
        font,
        natural.natural_width // 2,
        fill=(255, 255, 255, 255),
    )
    short = ui_module.fit_and_condense(
        "ЗВУК",
        font,
        1000,
        fill=(255, 255, 255, 255),
    )

    assert natural.horizontal_scale == 1.0
    assert short.horizontal_scale == 1.0
    assert condensed.horizontal_scale < 1.0
    assert condensed.image.width <= natural.natural_width // 2
    assert condensed.image.height == natural.image.height
    assert condensed.natural_height == natural.natural_height
    assert condensed.image.getchannel("A").getbbox() is not None


def test_title_menu_labels_share_each_row_baseline(ui_module):
    config = ui_module.load_asset_source()
    image, metrics = ui_module.render_title_menu("TITLE_MENU01", config, ui_module.FONT_PATH)
    alpha = image.getchannel("A")

    first_row = metrics[:5]
    assert {metric["baseline_y"] for metric in first_row} == {55}
    for metric, (_, x, max_width) in zip(first_row, ui_module.TITLE_ROWS[0][1]):
        half_width = max_width // 2
        bbox = alpha.crop((x - half_width, 0, x + half_width, 76)).getbbox()
        assert bbox is not None
        assert bbox[3] == 55


def test_selected_options_overlay_only_contains_selection_strip(ui_module):
    config = ui_module.load_asset_source()
    row = next(row for row in config["entries"] if row["name"] == "options_tab2_en")
    original = Image.open(ROOT / "build" / "steam" / "ui-assets" / "PARTS" / "images" / "0142-options_tab2_en.png").convert("RGBA")

    image, metrics = ui_module.render_options_tabs("options_tab2_en", row, original, ui_module.FONT_PATH)

    assert metrics == ()
    assert image.crop((0, 0, image.width, 88)).getchannel("A").getbbox() is None
    assert image.crop((0, 88, image.width, image.height)).getchannel("A").getbbox() is not None


def test_options_tab_labels_share_one_baseline(ui_module):
    config = ui_module.load_asset_source()
    row = next(row for row in config["entries"] if row["name"] == "options_tab_en")
    original = Image.open(ROOT / "build" / "steam" / "ui-assets" / "PARTS" / "images" / "0139-options_tab_en.png").convert("RGBA")

    _image, metrics = ui_module.render_options_tabs("options_tab_en", row, original, ui_module.FONT_PATH)

    assert len(metrics) == 10
    assert {metric["baseline_y"] for metric in metrics[1:]} == {80}


def test_message_control_states_use_crisp_equal_height_masks(ui_module):
    config = ui_module.load_asset_source()
    original = Image.open(ROOT / "build" / "steam" / "ui-assets" / "PARTS" / "images" / "0093-legacy_pt.png").convert("RGBA")

    _, metrics = ui_module.render_message_controls(config, original, ui_module.FONT_PATH)

    for row in range(4):
        heights = {
            metric["rendered_size"][1]
            for metric in metrics
            if metric["row"] == row
        }
        assert len(heights) == 1


def test_canonical_first_wave_is_draft_and_fully_covered(ui_module):
    config = ui_module.load_asset_source()
    rows = ui_module.first_wave_rows(config)
    coverage = {(row["archive"], row["name"]) for row in rows}

    assert config["schema_version"] == 1
    assert config["status"] == "draft"
    assert coverage == ui_module.EXPECTED_FIRST_WAVE
    assert all(row["status"] == "draft" for row in rows)
    assert all(row["archive"] in {"SYSCG.PAK", "PARTS.PAK"} for row in rows)
    assert not any(row["archive"] == "OTHCG.PAK" for row in rows)
    assert len(config["shared_text"]["system_menu"]["russian"]) == 9
    assert config["shared_text"]["gameplay_message_controls"]["russian"] == [
        "МЕНЮ", "ПРОПУСК", "АВТО", "ГОЛОС"
    ]

    by_key = {(row["archive"], row["name"]): row for row in config["entries"]}
    transparent_glow = by_key[("SYSCG.PAK", "TITLE_MENU01_GLOW")]
    assert transparent_glow["build_scope"] == "later"
    assert "fully transparent" in transparent_glow["build_scope_reason"]
    for key in ui_module.DEFERRED_SYSTEM_ICONS:
        assert by_key[key]["build_scope"] == "later"
        assert "must not guess" in by_key[key]["build_scope_reason"]


def test_interface_scope_adds_only_the_declared_final_assets(ui_module):
    config = ui_module.load_asset_source()
    rows = ui_module.scope_rows(config, "interface")
    coverage = {(row["archive"], row["name"]) for row in rows}

    assert coverage == ui_module.EXPECTED_FIRST_WAVE | ui_module.EXPECTED_INTERFACE_WAVE
    assert len(rows) == 28
    assert all(row["status"] == "draft" for row in rows)
    assert not any(row["archive"] == "OTHCG.PAK" for row in rows)


def test_gallery_page_replaces_only_the_number_cell(ui_module):
    config = ui_module.load_asset_source()
    row = next(row for row in config["entries"] if row["name"] == "CGModePAGE")
    original = Image.open(ROOT / "build" / "steam" / "ui-assets" / "SYSCG" / "images" / "0048-CGModePAGE.png").convert("RGBA")

    rendered, metrics = ui_module.render_gallery_page(row, original, ui_module.SANS_FONT_PATH)

    assert metrics[0]["text"] == "№"
    assert rendered.crop((0, 60, 88, 660)).tobytes() == original.crop((0, 60, 88, 660)).tobytes()
    assert rendered.crop((0, 0, 88, 60)).tobytes() != original.crop((0, 0, 88, 60)).tobytes()


def test_extra_header_preserves_digit_and_arrow_cells(ui_module):
    config = ui_module.load_asset_source()
    row = next(row for row in config["entries"] if row["name"] == "EXTRA_HEADER")
    original = Image.open(ROOT / "build" / "steam" / "ui-assets" / "PARTS" / "images" / "0060-EXTRA_HEADER.png").convert("RGBA")

    rendered, metrics = ui_module.render_extra_header(row, original, ui_module.FONT_PATH)

    assert [metric["text"] for metric in metrics] == ["ГАЛЕРЕЯ", "МУЗЫКА", "ПРОГРЕСС", "№"]
    assert rendered.crop((0, 420, 390, 696)).tobytes() == original.crop((0, 420, 390, 696)).tobytes()
    assert rendered.crop((500, 420, 632, 696)).tobytes() == original.crop((500, 420, 632, 696)).tobytes()


def test_install_and_restore_refuse_while_game_is_running(ui_module, monkeypatch):
    monkeypatch.setattr(ui_module, "game_is_running", lambda: True)
    with pytest.raises(SystemExit, match="game is running"):
        ui_module.install_artifacts({})
    with pytest.raises(SystemExit, match="game is running"):
        ui_module.restore_installed()


def _write_synthetic_pak(path, payloads, names, id_start=70000):
    block_size = 4
    flags = 0x200
    entry_count = len(payloads)
    names_blob = b"".join(name.encode("utf-8") + b"\0" for name in names)
    prefix_size = 36 + 4 + entry_count * 8 + len(names_blob)
    data_offset = prefix_size + (-prefix_size) % block_size

    offsets = []
    cursor = data_offset
    for payload in payloads:
        offsets.append((cursor // block_size, len(payload)))
        cursor += len(payload)
        cursor += (-cursor) % block_size

    header = struct.pack(
        "<9I",
        data_offset,
        entry_count,
        id_start,
        block_size,
        0,
        11,
        22,
        33,
        flags,
    )
    index = b"".join(struct.pack("<II", *item) for item in offsets)
    archive = bytearray(header + b"\0" * 4 + index + names_blob)
    archive.extend(b"\0" * (data_offset - len(archive)))
    for payload in payloads:
        archive.extend(payload)
        archive.extend(b"\0" * ((-len(archive)) % block_size))
    path.write_bytes(archive)


def test_fresh_pak_validation_preserves_layout_geometry_and_rgba(ui_module, tmp_path):
    palette = bytes(
        channel
        for index in range(256)
        for channel in (index, 255 - index, index // 2, 255)
    )
    indexed = ui_module.CzImage(
        version=1,
        width=2,
        height=2,
        bpp=248,
        pixels=bytes((0, 1, 127, 255)),
        palette=palette,
        offset_x=-2,
        offset_y=3,
        canvas_width=8,
        canvas_height=9,
    )
    source_path = tmp_path / "source.PAK"
    built_path = tmp_path / "built.PAK"
    _write_synthetic_pak(
        source_path,
        [ui_module.encode_cz0(indexed), b"untouched-payload"],
        ["target", "untouched"],
    )

    source = ui_module.Pak(source_path)
    original = ui_module.decode_cz(source.read_entry(0))
    rendered = Image.frombytes(
        "RGBA",
        (2, 2),
        bytes((10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160)),
    )
    payload = ui_module.encode_rgba_replacement(original, rendered)
    expected = ui_module.ReplacementPayload(
        index=0,
        entry_id=source.entries[0].entry_id,
        name="target",
        payload=payload,
        rgba=rendered.tobytes(),
        source_geometry=ui_module._geometry(original),
    )
    source.build(built_path, {0: payload})

    result = ui_module.validate_built_archive(source_path, built_path, (expected,))
    assert result == {
        "fresh_pak_readback": True,
        "entry_count": 2,
        "replacement_count": 1,
        "untouched_payload_count": 1,
        "layout_match": True,
        "payload_bytes_match": True,
        "rgba_pixels_match": True,
        "image_metadata_match": True,
    }

    rebuilt = ui_module.Pak(built_path)
    decoded = ui_module.decode_cz(rebuilt.read_entry(0))
    assert decoded.version == 0
    assert decoded.bpp == 32
    assert ui_module._geometry(decoded) == ui_module._geometry(original)
    assert ui_module.rgba_pixels(decoded) == rendered.tobytes()
    assert rebuilt.read_entry(1) == source.read_entry(1)

    damaged = bytearray(built_path.read_bytes())
    damaged[rebuilt.entries[0].offset + rebuilt.entries[0].size - 1] ^= 1
    built_path.write_bytes(damaged)
    with pytest.raises(ValueError, match="replacement payload bytes differ"):
        ui_module.validate_built_archive(source_path, built_path, (expected,))
