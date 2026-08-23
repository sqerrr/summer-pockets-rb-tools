"""Build and optionally install the first-wave Russian LUCA UI image archives."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from luca import Pak
from luca_image import CzImage, decode_cz, encode_cz0, rgba_pixels


ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = ROOT / "Summer Pockets REFLECTION BLUE_Steam/files/image"
BUILD_ROOT = ROOT / "build/steam"
ASSET_SOURCE = ROOT / "translation/ui/baked-assets.json"
RECEIPT_PATH = BUILD_ROOT / "ui-images-receipt.json"
IMAGE_DIR = BUILD_ROOT / "ui-russian-images"
FONT_PATH = Path("C:/Windows/Fonts/times.ttf")
SANS_FONT_PATH = Path("C:/Windows/Fonts/arial.ttf")
GAME_PROCESS = "SummerPocketsRB.exe"

PINNED_SHA256 = {
    "SYSCG.PAK": "560a6328c8ac96049a56d49fd0923cf543c3c3ef16e4c4997d3d7bc28b8a19c5",
    "PARTS.PAK": "d2e366030f104cca9ae8e0e1d4df03b192324728909aaaaef1fbf9f118b44485",
}


@dataclass(frozen=True)
class ArchiveSpec:
    name: str
    installed: Path
    backup: Path
    output: Path
    sha256: str


ARCHIVE_SPECS = {
    name: ArchiveSpec(
        name=name,
        installed=IMAGE_ROOT / name,
        backup=BUILD_ROOT / f"{Path(name).stem}.pristine.PAK",
        output=BUILD_ROOT / f"{Path(name).stem}.russian-ui.PAK",
        sha256=digest,
    )
    for name, digest in PINNED_SHA256.items()
}

EXPECTED_FIRST_WAVE = {
    ("SYSCG.PAK", "TITLE_MENU01"),
    ("SYSCG.PAK", "TITLE_MENU01B"),
    ("SYSCG.PAK", "TITLE_MENU01B_GLOW"),
    ("PARTS.PAK", "legacy_pt"),
    ("PARTS.PAK", "options_tab_en"),
    ("PARTS.PAK", "options_tab2_en"),
    ("PARTS.PAK", "load_bg"),
    ("PARTS.PAK", "save_bg"),
    ("PARTS.PAK", "systemmenuen"),
}

EXPECTED_INTERFACE_WAVE = {
    ("PARTS.PAK", "ext_pten"),
    ("PARTS.PAK", "EXTRA_HEADER"),
    ("PARTS.PAK", "RECORD_FRAME1"),
    ("PARTS.PAK", "RECORD_FRAME2"),
    *(("SYSCG.PAK", f"CGM_NAME{index:02d}en") for index in range(11)),
    ("SYSCG.PAK", "CGM_SELECTen"),
    ("SYSCG.PAK", "CGModePAGE"),
    ("SYSCG.PAK", "MCM_INFO__en"),
    ("SYSCG.PAK", "MCM_INFO_2__en"),
}

# These atlases have ten source labels, but their canonical reference currently
# resolves to a different nine-label list. They remain deferred rather than
# receiving guessed Russian strings or labels mapped to the wrong icons.
DEFERRED_SYSTEM_ICONS = {
    ("PARTS.PAK", "system_icon_1280_en"),
    ("PARTS.PAK", "system_icon_1920_en"),
}

TITLE_ROWS = (
    (39, (("START", 333, 190), ("LOAD", 626, 190), ("OPTIONS", 950, 250), ("MANUAL", 1291, 250), ("EXIT", 1615, 180))),
    (115, (("ALKA", 333, 190), ("LOAD", 626, 190), ("OPTIONS", 950, 250), ("MANUAL", 1291, 250), ("EXIT", 1615, 180))),
    (191, (("Pocket", 333, 190), ("LOAD", 626, 190), ("OPTIONS", 950, 250), ("MANUAL", 1291, 250), ("EXIT", 1615, 180))),
    (267, (("START", 302, 165), ("ALKA", 499, 150), ("Pocket", 698, 165), ("LOAD", 901, 165), ("OPTIONS", 1121, 190), ("MANUAL", 1354, 200), ("EXIT", 1626, 150))),
    (344, (("GALLERY", 612, 270), ("MUSIC", 963, 220), ("RECORD", 1317, 270))),
    (420, (("ReSTART", 438, 270), ("OPTIONS", 812, 270), ("MANUAL", 1194, 270), ("EXIT", 1537, 180))),
)
TITLE_BASELINE_OFFSET = 16
TITLE_GLOW_PADDING = 18

OPTION_CELLS = (
    (0, 432),
    (432, 578),
    (578, 720),
    (720, 867),
    (867, 1030),
    (1030, 1178),
    (1178, 1399),
    (1399, 1567),
    (1567, 1726),
    (1726, 1903),
)

SYSTEM_MENU_COLUMNS = ((26, 317), (331, 631), (668, 946), (983, 1261), (1298, 1576))
SYSTEM_MENU_BANDS = ((224, 276), (540, 592), (852, 908), (1166, 1223))
MESSAGE_CONTROL_CELL_WIDTH = 240
MESSAGE_CONTROL_CELL_HEIGHT = 60
SAVE_LOAD_BG_BOXES = {
    "load_bg": (
        (15, 333, 70, 520),
        (15, 722, 70, 908),
        (1851, 334, 1907, 520),
        (1851, 727, 1907, 913),
    ),
    "save_bg": (
        (15, 337, 70, 518),
        (15, 726, 70, 906),
        (1851, 336, 1907, 516),
        (1851, 729, 1907, 909),
    ),
}


@dataclass(frozen=True)
class FittedText:
    image: Image.Image
    natural_width: int
    natural_height: int
    horizontal_scale: float


@dataclass(frozen=True)
class RenderedAsset:
    archive: str
    row: dict
    image: Image.Image
    metrics: tuple[dict, ...]
    source_geometry: tuple[int, int, int, int, int, int]
    source_codec: str


@dataclass(frozen=True)
class ReplacementPayload:
    index: int
    entry_id: int
    name: str
    payload: bytes
    rgba: bytes
    source_geometry: tuple[int, int, int, int, int, int]


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_asset_source(path: Path = ASSET_SOURCE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported baked UI asset schema")
    if data.get("status") != "draft":
        raise ValueError("baked UI assets must remain draft until explicit user approval")

    archive_hashes = data.get("archive_sha256")
    if not isinstance(archive_hashes, dict):
        raise ValueError("baked UI source has no archive_sha256 map")
    for archive, expected in PINNED_SHA256.items():
        if archive_hashes.get(archive) != "sha256:" + expected:
            raise ValueError(f"canonical pristine hash changed for {archive}")

    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("baked UI source entries must be a list")
    seen = set()
    first_wave = set()
    interface_wave = set()
    rows_by_key = {}
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError("baked UI entry is not an object")
        key = (row.get("archive"), row.get("name"))
        if key in seen:
            raise ValueError(f"duplicate baked UI entry: {key}")
        seen.add(key)
        rows_by_key[key] = row
        if row.get("build_scope") != "first_wave":
            if row.get("build_scope") == "interface":
                if row.get("status") != "draft":
                    raise ValueError(f"interface entry is not draft: {key}")
                if key[0] not in PINNED_SHA256:
                    raise ValueError(f"interface archive is outside SYSCG/PARTS scope: {key}")
                interface_wave.add(key)
            continue
        if row.get("status") != "draft":
            raise ValueError(f"first-wave entry is not draft: {key}")
        if key[0] not in PINNED_SHA256:
            raise ValueError(f"first-wave archive is outside SYSCG/PARTS scope: {key}")
        first_wave.add(key)

    if first_wave != EXPECTED_FIRST_WAVE:
        missing = sorted(EXPECTED_FIRST_WAVE - first_wave)
        unsupported = sorted(first_wave - EXPECTED_FIRST_WAVE)
        raise ValueError(f"first-wave coverage mismatch; missing={missing}, unsupported={unsupported}")
    if interface_wave != EXPECTED_INTERFACE_WAVE:
        missing = sorted(EXPECTED_INTERFACE_WAVE - interface_wave)
        unsupported = sorted(interface_wave - EXPECTED_INTERFACE_WAVE)
        raise ValueError(f"interface-wave coverage mismatch; missing={missing}, unsupported={unsupported}")

    for key in DEFERRED_SYSTEM_ICONS:
        row = rows_by_key.get(key)
        if row is None or row.get("build_scope") != "later" or not row.get("build_scope_reason"):
            raise ValueError(f"deferred system icon lacks a precise reason: {key}")
    return data


def first_wave_rows(config: dict) -> tuple[dict, ...]:
    rows = tuple(row for row in config["entries"] if row.get("build_scope") == "first_wave")
    return tuple(sorted(rows, key=lambda row: (row["archive"], row["index"])))


def scope_rows(config: dict, scope: str) -> tuple[dict, ...]:
    if scope == "first_wave":
        return first_wave_rows(config)
    if scope != "interface":
        raise ValueError(f"unsupported baked UI scope: {scope}")
    rows = tuple(row for row in config["entries"] if row.get("build_scope") in {"first_wave", "interface"})
    return tuple(sorted(rows, key=lambda row: (row["archive"], row["index"])))


def fit_and_condense(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    *,
    fill: tuple[int, int, int, int],
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
    glow_color: tuple[int, int, int, int] | None = None,
    glow_radius: float = 0,
) -> FittedText:
    """Render at a fixed cap height and condense only the horizontal axis."""
    if not text or max_width <= 0:
        raise ValueError("text and max_width must be non-empty and positive")
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = measure.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    padding = max(4, stroke_width + int(glow_radius * 3) + 2)
    width = bbox[2] - bbox[0] + padding * 2
    height = bbox[3] - bbox[1] + padding * 2
    origin = (padding - bbox[0], padding - bbox[1])

    patch = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if glow_color is not None and glow_radius > 0:
        mask = Image.new("L", patch.size, 0)
        ImageDraw.Draw(mask).text(origin, text, font=font, fill=255, stroke_width=stroke_width)
        glow = mask.filter(ImageFilter.GaussianBlur(glow_radius))
        if glow_color[3] != 255:
            glow = glow.point(lambda value: round(value * glow_color[3] / 255))
        layer = Image.new("RGBA", patch.size, glow_color[:3] + (0,))
        layer.putalpha(glow)
        patch = Image.alpha_composite(patch, layer)

    ImageDraw.Draw(patch).text(
        origin,
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill or fill,
    )
    visible = patch.getchannel("A").getbbox()
    if visible is None:
        raise ValueError(f"rendered text is empty: {text!r}")
    patch = patch.crop(visible)
    natural_width, natural_height = patch.size
    scale = min(1.0, max_width / natural_width)
    if scale < 1.0:
        patch = patch.resize((max(1, round(natural_width * scale)), natural_height), Image.Resampling.LANCZOS)
    return FittedText(patch, natural_width, natural_height, scale)


def fit_and_condense_on_baseline(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    *,
    fill: tuple[int, int, int, int],
) -> tuple[FittedText, int]:
    bbox = font.getbbox(text, anchor="ls")
    padding = 4
    width = bbox[2] - bbox[0] + padding * 2
    height = bbox[3] - bbox[1] + padding * 2
    baseline = padding - bbox[1]
    patch = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(patch).text(
        (padding - bbox[0], baseline),
        text,
        font=font,
        fill=fill,
        anchor="ls",
    )
    visible = patch.getchannel("A").getbbox()
    if visible is None:
        raise ValueError(f"rendered text is empty: {text!r}")
    baseline -= visible[1]
    patch = patch.crop(visible)
    natural_width, natural_height = patch.size
    scale = min(1.0, max_width / natural_width)
    if scale < 1.0:
        patch = patch.resize((max(1, round(natural_width * scale)), natural_height), Image.Resampling.LANCZOS)
    return FittedText(patch, natural_width, natural_height, scale), baseline


def _place_center(canvas: Image.Image, patch: Image.Image, center: tuple[float, float]) -> None:
    x = round(center[0] - patch.width / 2)
    y = round(center[1] - patch.height / 2)
    canvas.alpha_composite(patch, (x, y))


def _place_title_label(
    canvas: Image.Image,
    patch: Image.Image,
    *,
    center_x: float,
    baseline_y: float,
    glyph_height: int,
    glow: bool,
) -> None:
    x = round(center_x - patch.width / 2)
    glyph_top = TITLE_GLOW_PADDING if glow else 0
    y = round(baseline_y - glyph_height - glyph_top)
    canvas.alpha_composite(patch, (x, y))


def _metric(text: str, fitted: FittedText, center: tuple[float, float]) -> dict:
    return {
        "text": text,
        "center": [round(center[0], 3), round(center[1], 3)],
        "natural_width": fitted.natural_width,
        "natural_height": fitted.natural_height,
        "horizontal_scale": round(fitted.horizontal_scale, 6),
        "rendered_size": list(fitted.image.size),
    }


def _selected_glow(glyph: Image.Image) -> Image.Image:
    padding = TITLE_GLOW_PADDING
    mask = Image.new("L", (glyph.width + padding * 2, glyph.height + padding * 2), 0)
    mask.paste(glyph.getchannel("A"), (padding, padding))
    halo = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(5))
    patch = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    halo_layer = Image.new("RGBA", mask.size, (185, 225, 255, 0))
    halo_layer.putalpha(halo.point(lambda value: round(value * 0.8)))
    patch = Image.alpha_composite(patch, halo_layer)
    text_layer = Image.new("RGBA", mask.size, (255, 255, 255, 0))
    text_layer.putalpha(mask)
    patch = Image.alpha_composite(patch, text_layer)
    return patch


def render_title_menu(name: str, config: dict, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    mapping = dict(zip(config["shared_text"]["title_menu"]["english"], config["shared_text"]["title_menu"]["russian"]))
    height = 648 if name == "TITLE_MENU01_GLOW" else 456
    canvas = Image.new("RGBA", (1920, height), (0, 0, 0, 0))
    font = ImageFont.truetype(str(font_path), 44)
    base_color = (72, 162, 255, 255) if name.startswith("TITLE_MENU01") and "B" not in name else (27, 69, 140, 255)
    glow = name.endswith("_GLOW")
    metrics = []
    for y, labels in TITLE_ROWS:
        for english, x, max_width in labels:
            russian = mapping[english]
            fitted = fit_and_condense(russian, font, max_width, fill=base_color)
            if glow:
                patch = _selected_glow(fitted.image)
            else:
                patch = fitted.image
            baseline = y + TITLE_BASELINE_OFFSET
            _place_title_label(
                canvas,
                patch,
                center_x=x,
                baseline_y=baseline,
                glyph_height=fitted.image.height,
                glow=glow,
            )
            metric = _metric(russian, fitted, (x, y))
            metric["baseline_y"] = baseline
            metrics.append(metric)
    return canvas, tuple(metrics)


def _median_inpaint(image: Image.Image, boxes: tuple[tuple[int, int, int, int], ...], size: int = 15) -> Image.Image:
    result = image.copy()
    radius = size // 2
    for box in boxes:
        expanded = (
            max(0, box[0] - radius),
            max(0, box[1] - radius),
            min(image.width, box[2] + radius),
            min(image.height, box[3] + radius),
        )
        filtered = image.crop(expanded).filter(ImageFilter.MedianFilter(size))
        local = (
            box[0] - expanded[0],
            box[1] - expanded[1],
            box[2] - expanded[0],
            box[3] - expanded[1],
        )
        result.paste(filtered.crop(local), box)
    return result


def render_options_tabs(name: str, row: dict, original: Image.Image, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    labels = row["proposed_russian"]
    selected = name == "options_tab2_en"
    if len(labels) != (9 if selected else 10):
        raise ValueError(f"unexpected canonical options label count for {name}")

    if selected:
        canvas = Image.new("RGBA", original.size, (0, 0, 0, 0))
        canvas.alpha_composite(original.crop((0, 88, original.width, original.height)), (0, 88))
        return canvas, ()
    else:
        canvas = original.copy()
        draw = ImageDraw.Draw(canvas)
        for left, right in OPTION_CELLS:
            draw.rectangle((left + 7, 7, right - 8, 94), fill=(0, 173, 190, 255))
        cells = OPTION_CELLS

    metrics = []
    for index, (text, (left, right)) in enumerate(zip(labels, cells)):
        title = not selected and index == 0
        font = ImageFont.truetype(str(font_path), 72 if title else 43)
        if title:
            fitted = fit_and_condense(text, font, right - left - 18, fill=(255, 255, 255, 255))
            center = ((left + right) / 2, 65)
            _place_center(canvas, fitted.image, center)
            metrics.append(_metric(text, fitted, center))
        else:
            fitted, baseline_offset = fit_and_condense_on_baseline(
                text,
                font,
                right - left - 18,
                fill=(255, 255, 255, 255),
            )
            baseline_y = 80
            x = round((left + right - fitted.image.width) / 2)
            y = round(baseline_y - baseline_offset)
            canvas.alpha_composite(fitted.image, (x, y))
            metric = _metric(text, fitted, ((left + right) / 2, baseline_y))
            metric["baseline_y"] = baseline_y
            metrics.append(metric)
    return canvas, tuple(metrics)


def _quadrant_alpha_boxes(image: Image.Image) -> tuple[tuple[int, int, int, int], ...]:
    alpha = image.getchannel("A")
    width, height = image.size
    regions = (
        (0, 0, width // 2, height // 2),
        (0, height // 2, width // 2, height),
        (width // 2, 0, width, height // 2),
        (width // 2, height // 2, width, height),
    )
    boxes = []
    for region in regions:
        local = alpha.crop(region).getbbox()
        if local is None:
            raise ValueError("save/load source is missing an edge heading")
        boxes.append((local[0] + region[0], local[1] + region[1], local[2] + region[0], local[3] + region[1]))
    return tuple(boxes)


def render_edge_headings(name: str, row: dict, original: Image.Image, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    text = row["proposed_russian"][0]
    canvas = Image.new("RGBA", original.size, (0, 0, 0, 0))
    boxes = _quadrant_alpha_boxes(original)
    font = ImageFont.truetype(str(font_path), round(original.width * 0.038))
    accent = (76, 157, 255, 255) if name.startswith("load_") else (255, 126, 180, 255)
    metrics = []
    for index, box in enumerate(boxes):
        max_length = box[3] - box[1]
        fitted = fit_and_condense(
            text,
            font,
            max_length,
            fill=(255, 255, 255, 255),
            stroke_width=max(1, round(original.width / 960)),
            stroke_fill=accent,
            glow_color=accent[:3] + (150,),
            glow_radius=max(1, original.width / 960),
        )
        angle = 90 if index < 2 else -90
        rotated = fitted.image.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        _place_center(canvas, rotated, center)
        metrics.append(_metric(text, fitted, center) | {"rotation": angle, "anchor_box": list(box)})
    return canvas, tuple(metrics)


def _restore_edge_strips(image: Image.Image) -> None:
    strip_width = 120
    fade_width = 36
    left_patch = image.crop((strip_width, 0, strip_width * 2, image.height))
    right_patch = image.crop((image.width - strip_width * 2, 0, image.width - strip_width, image.height))

    left_mask = Image.new("L", (strip_width, image.height), 255)
    right_mask = Image.new("L", (strip_width, image.height), 255)
    left_draw = ImageDraw.Draw(left_mask)
    right_draw = ImageDraw.Draw(right_mask)
    for offset in range(fade_width):
        alpha = round(255 * (fade_width - 1 - offset) / (fade_width - 1))
        left_draw.line((strip_width - fade_width + offset, 0, strip_width - fade_width + offset, image.height), fill=alpha)
        right_draw.line((fade_width - 1 - offset, 0, fade_width - 1 - offset, image.height), fill=alpha)
    image.paste(left_patch, (0, 0), left_mask)
    image.paste(right_patch, (image.width - strip_width, 0), right_mask)


def render_save_load_background(name: str, row: dict, original: Image.Image, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    if original.size != (1920, 1080):
        raise ValueError(f"{name} requires a 1920x1080 background")
    boxes = SAVE_LOAD_BG_BOXES[name]
    text = row["proposed_russian"][0]
    canvas = original.copy()
    _restore_edge_strips(canvas)

    font = ImageFont.truetype(str(font_path), 52)
    accent = (76, 157, 255, 255) if name == "load_bg" else (255, 126, 180, 255)
    metrics = []
    for index, box in enumerate(boxes):
        fitted = fit_and_condense(
            text,
            font,
            box[3] - box[1],
            fill=(255, 255, 255, 255),
            stroke_width=2,
            stroke_fill=accent,
            glow_color=accent[:3] + (150,),
            glow_radius=2,
        )
        angle = 90 if index < 2 else -90
        rotated = fitted.image.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        _place_center(canvas, rotated, center)
        metrics.append(_metric(text, fitted, center) | {"rotation": angle, "anchor_box": list(box)})
    return canvas, tuple(metrics)


def render_system_menu(config: dict, original: Image.Image, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    labels = config["shared_text"]["system_menu"]["russian"]
    if len(labels) != 9:
        raise ValueError("systemmenuen requires exactly nine canonical labels")
    boxes = tuple(
        (left, top, right, bottom)
        for top, bottom in SYSTEM_MENU_BANDS
        for left, right in SYSTEM_MENU_COLUMNS[: (5 if top < 600 else 4)]
    )
    canvas = _median_inpaint(original, boxes, 17)
    font = ImageFont.truetype(str(font_path), 43)
    metrics = []
    states = (
        (labels[:5], SYSTEM_MENU_COLUMNS, SYSTEM_MENU_BANDS[0], (180, 255, 255, 255)),
        (labels[:5], SYSTEM_MENU_COLUMNS, SYSTEM_MENU_BANDS[1], (255, 255, 255, 255)),
        (labels[5:], SYSTEM_MENU_COLUMNS[:4], SYSTEM_MENU_BANDS[2], (180, 255, 255, 255)),
        (labels[5:], SYSTEM_MENU_COLUMNS[:4], SYSTEM_MENU_BANDS[3], (255, 255, 255, 255)),
    )
    for state_labels, columns, band, color in states:
        for text, (left, right) in zip(state_labels, columns):
            fitted = fit_and_condense(
                text,
                font,
                right - left - 16,
                fill=color,
                stroke_width=1,
                stroke_fill=(0, 45, 90, 220),
            )
            center = ((left + right) / 2, (band[0] + band[1]) / 2)
            _place_center(canvas, fitted.image, center)
            metrics.append(_metric(text, fitted, center))
    return canvas, tuple(metrics)


def render_message_controls(config: dict, original: Image.Image, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    labels = config["shared_text"]["gameplay_message_controls"]["russian"]
    if len(labels) != 4 or original.size != (960, 240):
        raise ValueError("legacy_pt requires four labels in a 960x240 atlas")

    canvas = original.copy()
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(font_path), 36)
    states = (
        ((218, 226, 226, 140), (85, 117, 120, 120), None),
        ((255, 255, 255, 255), (0, 147, 161, 255), None),
        ((255, 255, 255, 255), (45, 200, 215, 255), None),
        ((255, 255, 255, 255), (45, 200, 215, 255), None),
    )
    metrics = []
    for row_index, text in enumerate(labels):
        top = row_index * MESSAGE_CONTROL_CELL_HEIGHT
        for column_index, (fill, stroke, glow) in enumerate(states):
            left = column_index * MESSAGE_CONTROL_CELL_WIDTH
            draw.rectangle((left + 48, top + 3, left + 180, top + 57), fill=(0, 0, 0, 0))
            fitted = fit_and_condense(
                text,
                font,
                120,
                fill=fill,
                stroke_width=2,
                stroke_fill=stroke,
                glow_color=glow,
                glow_radius=3 if glow else 0,
            )
            center = (left + 108, top + 30)
            _place_center(canvas, fitted.image, center)
            metrics.append(_metric(text, fitted, center) | {
                "row": row_index,
                "state_column": column_index,
            })
    return canvas, tuple(metrics)


def _alpha_bbox_in_region(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    local = image.getchannel("A").crop(box).getbbox()
    if local is None:
        raise ValueError(f"expected visible pixels in region {box}")
    return (
        local[0] + box[0],
        local[1] + box[1],
        local[2] + box[0],
        local[3] + box[1],
    )


def render_extra_completion(row: dict, original: Image.Image, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    if original.size != (592, 132) or len(row["proposed_russian"]) != 3:
        raise ValueError("ext_pten canonical geometry or text count changed")
    canvas = Image.new("RGBA", original.size, (0, 0, 0, 0))
    canvas.alpha_composite(original.crop((540, 0, original.width, original.height)), (540, 0))
    font = ImageFont.truetype(str(font_path), 45)
    metrics = []
    for text, region in zip(row["proposed_russian"][:2], ((0, 0, 540, 66), (0, 66, 540, 132))):
        source_box = _alpha_bbox_in_region(original, region)
        fitted = fit_and_condense(text, font, source_box[2] - source_box[0], fill=(255, 255, 255, 255))
        center = ((source_box[0] + source_box[2]) / 2, (source_box[1] + source_box[3]) / 2)
        _place_center(canvas, fitted.image, center)
        metrics.append(_metric(text, fitted, center) | {"source_box": list(source_box)})
    return canvas, tuple(metrics)


def render_extra_header(row: dict, original: Image.Image, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    if original.size != (632, 696) or len(row["proposed_russian"]) != 4:
        raise ValueError("EXTRA_HEADER canonical geometry or text count changed")
    canvas = original.copy()
    ImageDraw.Draw(canvas).rectangle((0, 0, original.width - 1, 419), fill=(0, 0, 0, 0))
    font = ImageFont.truetype(str(font_path), 80)
    regions = ((0, 20, 632, 115), (0, 125, 632, 230), (0, 240, 632, 350))
    metrics = []
    for text, region in zip(row["proposed_russian"][:3], regions):
        source_box = _alpha_bbox_in_region(original, region)
        fitted = fit_and_condense(text, font, 540, fill=(255, 255, 255, 255))
        center = (48 + fitted.image.width / 2, (source_box[1] + source_box[3]) / 2)
        canvas.alpha_composite(fitted.image, (48, round(center[1] - fitted.image.height / 2)))
        metrics.append(_metric(text, fitted, center) | {"source_box": list(source_box)})

    number_box = _alpha_bbox_in_region(original, (390, 620, 500, 696))
    ImageDraw.Draw(canvas).rectangle((390, 620, 499, 695), fill=(0, 0, 0, 0))
    number_font = ImageFont.truetype(str(SANS_FONT_PATH), 47)
    number = fit_and_condense(
        row["proposed_russian"][3],
        number_font,
        92,
        fill=(255, 255, 255, 255),
        stroke_width=3,
        stroke_fill=(0, 0, 0, 255),
    )
    number_center = ((number_box[0] + number_box[2]) / 2, (number_box[1] + number_box[3]) / 2)
    _place_center(canvas, number.image, number_center)
    metrics.append(_metric(row["proposed_russian"][3], number, number_center) | {"source_box": list(number_box)})
    return canvas, tuple(metrics)


def render_record_frame(name: str, row: dict, original: Image.Image, sans_font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    if original.size != (1632, 72) or row["proposed_russian"] != ["№"]:
        raise ValueError(f"{name} canonical geometry or text changed")
    canvas = original.copy()
    background = original.getpixel((180, 35))
    ImageDraw.Draw(canvas).rectangle((62, 7, 150, 65), fill=background)
    color = (255, 255, 255, 255) if name == "RECORD_FRAME2" else (177, 190, 192, 255)
    font = ImageFont.truetype(str(sans_font_path), 38)
    fitted = fit_and_condense("№", font, 68, fill=color)
    center = (103, 36)
    _place_center(canvas, fitted.image, center)
    return canvas, (_metric("№", fitted, center),)


def render_gallery_heading(row: dict, original: Image.Image, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    if original.size != (1704, 60) or len(row["proposed_russian"]) != 1:
        raise ValueError(f"{row['name']} canonical geometry or text changed")
    canvas = original.copy()
    background = original.getpixel((852, 1))
    ImageDraw.Draw(canvas).rectangle((604, 0, 1100, 59), fill=background)
    font = ImageFont.truetype(str(font_path), 43)
    text = row["proposed_russian"][0]
    fitted = fit_and_condense(text, font, 480, fill=(255, 255, 255, 255))
    center = (852, 30)
    _place_center(canvas, fitted.image, center)
    return canvas, (_metric(text, fitted, center),)


def _difference_mask(left: Image.Image, right: Image.Image) -> Image.Image:
    channels = ImageChops.difference(left, right).split()
    maximum = channels[0]
    for channel in channels[1:]:
        maximum = ImageChops.lighter(maximum, channel)
    return maximum.point(lambda value: 255 if value else 0)


def render_gallery_selection(
    pak: Pak,
    row: dict,
    config: dict,
    original: Image.Image,
    font_path: Path,
) -> tuple[Image.Image, tuple[dict, ...]]:
    if original.size != (4152, 684):
        raise ValueError("CGM_SELECTen canonical geometry changed")
    language_variants = []
    for index, expected_name in ((45, "CGM_SELECT"), (47, "CGM_SELECTzc")):
        entry = pak.entries[index]
        if entry.name != expected_name:
            raise ValueError(f"gallery selection companion changed at index {index}")
        decoded = decode_cz(pak.read_entry(entry))
        language_variants.append(Image.frombytes("RGBA", (decoded.width, decoded.height), rgba_pixels(decoded)))

    mask = Image.new("L", original.size, 0)
    label_columns = tuple(range(10)) + (11,)
    label_boxes = []
    for state_row in range(2):
        top = state_row * 342
        for column in label_columns:
            box = (column * 346, top + 270, (column + 1) * 346, top + 330)
            label_boxes.append(box)
            english = original.crop(box)
            differs_both = ImageChops.multiply(
                _difference_mask(english, language_variants[0].crop(box)),
                _difference_mask(english, language_variants[1].crop(box)),
            )
            mask.paste(differs_both, box)
    mask = mask.filter(ImageFilter.MaxFilter(3))
    canvas = original.copy()
    for box in label_boxes:
        clone_box = (box[0], box[1] - 45, box[2], box[3] - 45)
        cloned = original.crop(clone_box).filter(ImageFilter.GaussianBlur(1))
        canvas.paste(cloned, box, mask.crop(box))
    badge_layer = Image.new("RGBA", original.size, (0, 0, 0, 0))
    badge_draw = ImageDraw.Draw(badge_layer)
    for state_row in range(2):
        top = state_row * 342
        for column in label_columns:
            badge_draw.rounded_rectangle(
                (column * 346 + 14, top + 279, column * 346 + 332, top + 327),
                radius=12,
                fill=(18, 24, 42, 225),
                outline=(255, 255, 255, 85),
                width=1,
            )
    canvas = Image.alpha_composite(canvas, badge_layer)

    labels = [
        candidate["proposed_russian"][0]
        for candidate in sorted(config["entries"], key=lambda item: item["index"])
        if candidate.get("build_scope") == "interface" and candidate["name"].startswith("CGM_NAME")
    ]
    if len(labels) != 11:
        raise ValueError("CGM_SELECTen requires eleven canonical gallery labels")
    font = ImageFont.truetype(str(font_path), 22)
    metrics = []
    for state_row in range(2):
        for label, column in zip(labels, label_columns):
            fitted = fit_and_condense(
                label,
                font,
                316,
                fill=(255, 255, 255, 255),
                stroke_width=2,
                stroke_fill=(20, 28, 48, 255),
                glow_color=(0, 0, 0, 180),
                glow_radius=1,
            )
            center = (column * 346 + 173, state_row * 342 + 306)
            _place_center(canvas, fitted.image, center)
            metrics.append(_metric(label, fitted, center) | {"state_row": state_row, "column": column})
    return canvas, tuple(metrics)


def render_gallery_page(row: dict, original: Image.Image, sans_font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    if original.size != (88, 660) or row["proposed_russian"] != ["№"]:
        raise ValueError("CGModePAGE canonical geometry or text changed")
    canvas = original.copy()
    background = original.getpixel((87, 0))
    ImageDraw.Draw(canvas).rectangle((0, 0, 87, 59), fill=background)
    font = ImageFont.truetype(str(sans_font_path), 47)
    fitted = fit_and_condense(
        "№",
        font,
        76,
        fill=(255, 255, 255, 255),
        stroke_width=3,
        stroke_fill=(0, 0, 0, 255),
    )
    center = (42, 30)
    _place_center(canvas, fitted.image, center)
    return canvas, (_metric("№", fitted, center),)


def _occupied_runs(values: list[bool], max_gap: int = 0) -> list[tuple[int, int]]:
    exact = []
    start = None
    for index, value in enumerate(values + [False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            exact.append((start, index))
            start = None
    merged = []
    for start, end in exact:
        if merged and start - merged[-1][1] <= max_gap:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _music_credit_mask_and_lines(image: Image.Image, first_track: int, track_count: int) -> tuple[Image.Image, dict[int, tuple[tuple[int, int, int, int], ...]]]:
    mask = Image.new("L", image.size, 0)
    mask_pixels = mask.load()
    pixels = image.load()
    lines_by_track = {}
    for offset in range(track_count):
        track_number = first_track + offset
        slot = offset + (1 if first_track == 1 else 0)
        top = slot * 90
        occupied_y = [False] * 90
        for y in range(top, top + 90):
            for x in range(480, image.width):
                red, green, blue, alpha = pixels[x, y]
                if alpha and blue - red > 12 and green - red > 4:
                    mask_pixels[x, y] = 255
                    occupied_y[y - top] = True
        line_boxes = []
        for local_top, local_bottom in _occupied_runs(occupied_y, max_gap=4):
            region = (480, top + local_top, image.width, top + local_bottom)
            local = mask.crop(region).getbbox()
            if local is None:
                continue
            line_boxes.append((
                local[0] + region[0],
                local[1] + region[1],
                local[2] + region[0],
                local[3] + region[1],
            ))
        if not 1 <= len(line_boxes) <= 2:
            raise ValueError(f"track {track_number} has an unexpected credit-line count: {len(line_boxes)}")
        lines_by_track[track_number] = tuple(line_boxes)
    return mask, lines_by_track


def _format_credit(label: str, value: str, translated_labels: dict[str, str], translated: bool) -> str:
    display_label = translated_labels[label] if translated else label
    if label == "Adapted from German Folksong":
        return f"({display_label} “{value}”)"
    return f"{display_label}: {value}"


def _partition_credit_fields(
    fields: list[tuple[str, str]],
    line_boxes: tuple[tuple[int, int, int, int], ...],
    font: ImageFont.FreeTypeFont,
    translated_labels: dict[str, str],
) -> tuple[tuple[tuple[str, str], ...], ...]:
    if len(line_boxes) == 1:
        return (tuple(fields),)
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    candidates = []
    for split in range(1, len(fields)):
        groups = (fields[:split], fields[split:])
        scales = []
        for group, box in zip(groups, line_boxes):
            text = "   ".join(_format_credit(label, value, translated_labels, False) for label, value in group)
            expected_width = measure.textlength(text, font=font)
            scales.append((box[2] - box[0]) / expected_width)
        score = abs(scales[0] - scales[1]) / max(scales)
        candidates.append((score, split))
    _, split = min(candidates)
    return (tuple(fields[:split]), tuple(fields[split:]))


def render_music_info(name: str, config: dict, original: Image.Image, font_path: Path) -> tuple[Image.Image, tuple[dict, ...]]:
    first_track, track_count = (1, 45) if name == "MCM_INFO__en" else (46, 15)
    expected_height = 4320 if first_track == 1 else 1350
    if original.size != (1768, expected_height):
        raise ValueError(f"{name} canonical geometry changed")
    tracks = {track["n"]: track for track in config["shared_text"]["music_tracks"]}
    translated_labels = config["shared_text"]["music_credit_labels"]
    mask, lines_by_track = _music_credit_mask_and_lines(original, first_track, track_count)
    canvas = original.copy()
    canvas.paste((0, 0, 0, 0), (0, 0, original.width, original.height), mask.filter(ImageFilter.MaxFilter(3)))
    font = ImageFont.truetype(str(font_path), 30)
    metrics = []
    for track_number in range(first_track, first_track + track_count):
        fields = list(tracks[track_number]["credits"].items())
        line_boxes = lines_by_track[track_number]
        groups = _partition_credit_fields(fields, line_boxes, font, translated_labels)
        for line_index, (group, source_box) in enumerate(zip(groups, line_boxes)):
            text = "   ".join(_format_credit(label, value, translated_labels, True) for label, value in group)
            fitted = fit_and_condense(
                text,
                font,
                original.width - source_box[0] - 20,
                fill=(184, 237, 255, 255),
            )
            center = (source_box[0] + fitted.image.width / 2, (source_box[1] + source_box[3]) / 2)
            _place_center(canvas, fitted.image, center)
            metrics.append(_metric(text, fitted, center) | {
                "track": track_number,
                "line": line_index,
                "source_box": list(source_box),
            })
    return canvas, tuple(metrics)


def _geometry(image: CzImage) -> tuple[int, int, int, int, int, int]:
    return (
        image.width,
        image.height,
        image.offset_x,
        image.offset_y,
        image.canvas_width or image.width,
        image.canvas_height or image.height,
    )


def _find_entry(pak: Pak, row: dict):
    index = row.get("index")
    if not isinstance(index, int) or not 0 <= index < pak.entry_count:
        raise ValueError(f"invalid PAK index in canonical row: {index}")
    entry = pak.entries[index]
    if entry.entry_id != row.get("entry_id") or entry.name != row.get("name"):
        raise ValueError(
            f"PAK identity mismatch at index {index}: expected {row.get('entry_id')}/{row.get('name')}, "
            f"got {entry.entry_id}/{entry.name}"
        )
    return entry


def render_asset(pak: Pak, row: dict, config: dict, font_path: Path) -> RenderedAsset:
    entry = _find_entry(pak, row)
    decoded = decode_cz(pak.read_entry(entry))
    geometry = _geometry(decoded)
    expected_geometry = row.get("geometry", {})
    if geometry[:2] != (expected_geometry.get("width"), expected_geometry.get("height")):
        raise ValueError(f"canonical geometry mismatch for {entry.name}: {geometry[:2]}")
    original = Image.frombytes("RGBA", (decoded.width, decoded.height), rgba_pixels(decoded))

    name = entry.name
    if name in {"TITLE_MENU01", "TITLE_MENU01_GLOW", "TITLE_MENU01B", "TITLE_MENU01B_GLOW"}:
        image, metrics = render_title_menu(name, config, font_path)
    elif name in {"options_tab_en", "options_tab2_en"}:
        image, metrics = render_options_tabs(name, row, original, font_path)
    elif name == "legacy_pt":
        image, metrics = render_message_controls(config, original, font_path)
    elif name in SAVE_LOAD_BG_BOXES:
        image, metrics = render_save_load_background(name, row, original, font_path)
    elif name in {"load_bg_text_1280", "load_bg_text_1920", "save_bg_text_1280", "save_bg_text_1920"}:
        image, metrics = render_edge_headings(name, row, original, font_path)
    elif name == "systemmenuen":
        image, metrics = render_system_menu(config, original, font_path)
    elif name == "ext_pten":
        image, metrics = render_extra_completion(row, original, font_path)
    elif name == "EXTRA_HEADER":
        image, metrics = render_extra_header(row, original, font_path)
    elif name in {"RECORD_FRAME1", "RECORD_FRAME2"}:
        image, metrics = render_record_frame(name, row, original, SANS_FONT_PATH)
    elif re.fullmatch(r"CGM_NAME\d{2}en", name):
        image, metrics = render_gallery_heading(row, original, font_path)
    elif name == "CGM_SELECTen":
        image, metrics = render_gallery_selection(pak, row, config, original, font_path)
    elif name == "CGModePAGE":
        image, metrics = render_gallery_page(row, original, SANS_FONT_PATH)
    elif name in {"MCM_INFO__en", "MCM_INFO_2__en"}:
        image, metrics = render_music_info(name, config, original, font_path)
    else:
        raise ValueError(f"unsupported baked UI asset: {row['archive']}:{name}")

    if image.mode != "RGBA" or image.size != (decoded.width, decoded.height):
        raise ValueError(f"renderer changed image geometry for {entry.name}")
    return RenderedAsset(
        archive=row["archive"],
        row=row,
        image=image,
        metrics=metrics,
        source_geometry=geometry,
        source_codec=f"CZ{decoded.version}",
    )


def encode_rgba_replacement(original: CzImage, image: Image.Image) -> bytes:
    if image.mode != "RGBA" or image.size != (original.width, original.height):
        raise ValueError("replacement must be RGBA with the source dimensions")
    return encode_cz0(
        CzImage(
            version=0,
            width=original.width,
            height=original.height,
            bpp=32,
            pixels=image.tobytes(),
            offset_x=original.offset_x,
            offset_y=original.offset_y,
            canvas_width=original.canvas_width,
            canvas_height=original.canvas_height,
        )
    )


def prepare_replacements(pak: Pak, rendered: tuple[RenderedAsset, ...]) -> tuple[dict, tuple[ReplacementPayload, ...], tuple[dict, ...]]:
    build_map = {}
    expected = []
    details = []
    for asset in rendered:
        entry = _find_entry(pak, asset.row)
        source_payload = pak.read_entry(entry)
        original = decode_cz(source_payload)
        payload = encode_rgba_replacement(original, asset.image)
        replacement = ReplacementPayload(
            index=entry.index,
            entry_id=entry.entry_id,
            name=entry.name,
            payload=payload,
            rgba=asset.image.tobytes(),
            source_geometry=asset.source_geometry,
        )
        build_map[entry.index] = payload
        expected.append(replacement)
        details.append(
            {
                "name": entry.name,
                "index": entry.index,
                "entry_id": entry.entry_id,
                "source_codec": asset.source_codec,
                "source_size": len(source_payload),
                "replacement_codec": "CZ0 RGBA",
                "replacement_size": len(payload),
                "replacement_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "geometry": {
                    "width": asset.source_geometry[0],
                    "height": asset.source_geometry[1],
                    "offset_x": asset.source_geometry[2],
                    "offset_y": asset.source_geometry[3],
                    "canvas_width": asset.source_geometry[4],
                    "canvas_height": asset.source_geometry[5],
                },
                "render_metrics": list(asset.metrics),
            }
        )
    return build_map, tuple(expected), tuple(details)


def validate_built_archive(source_path: Path, built_path: Path, replacements: tuple[ReplacementPayload, ...]) -> dict:
    """Validate layout and every payload through newly opened Pak instances."""
    source = Pak(source_path)
    built = Pak(built_path)
    header_fields = ("data_offset", "entry_count", "id_start", "block_size", "subdir_offset", "unknown2", "unknown3", "unknown4", "flags", "subdirectory")
    for field in header_fields:
        if getattr(source, field) != getattr(built, field):
            raise ValueError(f"PAK header metadata changed: {field}")
    source_layout = tuple((entry.index, entry.entry_id, entry.name) for entry in source.entries)
    built_layout = tuple((entry.index, entry.entry_id, entry.name) for entry in built.entries)
    if source_layout != built_layout:
        raise ValueError("PAK entry IDs, names, or order changed")

    expected_by_index = {item.index: item for item in replacements}
    if len(expected_by_index) != len(replacements):
        raise ValueError("duplicate replacement index")
    untouched = 0
    for source_entry, built_entry in zip(source.entries, built.entries):
        actual = built.read_entry(built_entry)
        replacement = expected_by_index.get(source_entry.index)
        if replacement is None:
            if actual != source.read_entry(source_entry):
                raise ValueError(f"untouched PAK payload changed: {source_entry.name}")
            untouched += 1
            continue
        if (replacement.entry_id, replacement.name) != (built_entry.entry_id, built_entry.name):
            raise ValueError(f"replacement identity changed: {replacement.name}")
        if actual != replacement.payload:
            raise ValueError(f"replacement payload bytes differ: {replacement.name}")
        decoded = decode_cz(actual)
        if decoded.version != 0 or decoded.bpp != 32:
            raise ValueError(f"replacement is not lossless CZ0 RGBA: {replacement.name}")
        if _geometry(decoded) != replacement.source_geometry:
            raise ValueError(f"replacement image metadata changed: {replacement.name}")
        if rgba_pixels(decoded) != replacement.rgba:
            raise ValueError(f"replacement RGBA pixels differ: {replacement.name}")
    return {
        "fresh_pak_readback": True,
        "entry_count": built.entry_count,
        "replacement_count": len(replacements),
        "untouched_payload_count": untouched,
        "layout_match": True,
        "payload_bytes_match": True,
        "rgba_pixels_match": True,
        "image_metadata_match": True,
    }


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "unnamed"


def _checkerboard(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGBA", size, (36, 42, 54, 255))
    draw = ImageDraw.Draw(image)
    tile = 20
    for y in range(0, size[1], tile):
        for x in range(0, size[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(58, 66, 80, 255))
    return image


def write_previews(rendered: tuple[RenderedAsset, ...], image_dir: Path, font_path: Path) -> tuple[str, ...]:
    image_dir.mkdir(parents=True, exist_ok=True)
    label_font = ImageFont.truetype(str(font_path), 18)
    contact_paths = []
    for archive in PINNED_SHA256:
        assets = tuple(item for item in rendered if item.archive == archive)
        archive_dir = image_dir / Path(archive).stem
        archive_dir.mkdir(parents=True, exist_ok=True)
        for item in assets:
            item.image.save(archive_dir / f"{item.row['index']:04d}-{_safe_name(item.row['name'])}.png")

        cell_width, cell_height, columns = 640, 360, 2
        rows = (len(assets) + columns - 1) // columns
        sheet = Image.new("RGB", (cell_width * columns, cell_height * rows), (24, 28, 36))
        draw = ImageDraw.Draw(sheet)
        for index, item in enumerate(assets):
            preview = _checkerboard((600, 310))
            thumbnail = item.image.copy()
            thumbnail.thumbnail((590, 300), Image.Resampling.LANCZOS)
            preview.alpha_composite(thumbnail, ((preview.width - thumbnail.width) // 2, (preview.height - thumbnail.height) // 2))
            x = index % columns * cell_width
            y = index // columns * cell_height
            sheet.paste(preview.convert("RGB"), (x + 20, y + 10))
            draw.text((x + 20, y + 326), f"{item.row['index']} / {item.row['entry_id']}  {item.row['name']}", font=label_font, fill=(235, 238, 244))
        contact_path = image_dir / f"{Path(archive).stem}-contact-sheet.png"
        sheet.save(contact_path)
        contact_paths.append(str(contact_path))
    return tuple(contact_paths)


def assert_pristine(path: Path, spec: ArchiveSpec) -> str:
    if not path.is_file():
        raise SystemExit(f"ERROR: pristine source is missing: {path}")
    actual = digest_file(path)
    if actual != spec.sha256:
        raise SystemExit(f"ERROR: wrong pristine {spec.name}: expected {spec.sha256}, got {actual}")
    return actual


def game_is_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS}", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return GAME_PROCESS.casefold() in result.stdout.casefold()


def _atomic_verified_copy(source: Path, destination: Path, expected_hash: str) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        shutil.copy2(source, temporary)
        actual = digest_file(temporary)
        if actual != expected_hash:
            raise ValueError(f"copied file hash mismatch for {destination.name}")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    actual = digest_file(destination)
    if actual != expected_hash:
        raise ValueError(f"installed file hash mismatch for {destination.name}")
    return actual


def ensure_pristine_backup(spec: ArchiveSpec) -> Path:
    if spec.backup.exists():
        assert_pristine(spec.backup, spec)
        return spec.backup
    assert_pristine(spec.installed, spec)
    _atomic_verified_copy(spec.installed, spec.backup, spec.sha256)
    assert_pristine(spec.backup, spec)
    return spec.backup


def select_source(spec: ArchiveSpec, require_backup: bool) -> Path:
    if spec.backup.exists():
        assert_pristine(spec.backup, spec)
        return spec.backup
    if require_backup:
        return ensure_pristine_backup(spec)
    assert_pristine(spec.installed, spec)
    return spec.installed


def install_artifacts(output_hashes: dict[str, str]) -> dict[str, str]:
    if game_is_running():
        raise SystemExit("ERROR: the game is running; UI archives were not installed")
    for spec in ARCHIVE_SPECS.values():
        assert_pristine(spec.backup, spec)
        if digest_file(spec.output) != output_hashes[spec.name]:
            raise ValueError(f"artifact hash changed before install: {spec.name}")

    installed = {}
    attempted = []
    try:
        for spec in ARCHIVE_SPECS.values():
            attempted.append(spec)
            installed[spec.name] = _atomic_verified_copy(spec.output, spec.installed, output_hashes[spec.name])
    except Exception:
        for spec in attempted:
            _atomic_verified_copy(spec.backup, spec.installed, spec.sha256)
        raise
    return installed


def restore_installed() -> None:
    if game_is_running():
        raise SystemExit("ERROR: the game is running; pristine UI archives were not restored")
    for spec in ARCHIVE_SPECS.values():
        assert_pristine(spec.backup, spec)
    for spec in ARCHIVE_SPECS.values():
        _atomic_verified_copy(spec.backup, spec.installed, spec.sha256)
    print("Restored pristine SYSCG.PAK and PARTS.PAK")


def build_archive(spec: ArchiveSpec, source_path: Path, rendered: tuple[RenderedAsset, ...]) -> dict:
    source = Pak(source_path)
    build_map, replacements, details = prepare_replacements(source, rendered)
    temporary = spec.output.with_name(spec.output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        source.build(temporary, build_map)
        validation = validate_built_archive(source_path, temporary, replacements)
        output_hash = digest_file(temporary)
        os.replace(temporary, spec.output)
    finally:
        if temporary.exists():
            temporary.unlink()
    if digest_file(spec.output) != output_hash:
        raise ValueError(f"artifact hash changed after finalization: {spec.name}")
    return {
        "archive": spec.name,
        "source": str(source_path),
        "source_sha256": "sha256:" + spec.sha256,
        "output": str(spec.output),
        "output_sha256": "sha256:" + output_hash,
        "entry_count": source.entry_count,
        "replacement_count": len(replacements),
        "validation": validation,
        "entries": list(details),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, default=FONT_PATH)
    parser.add_argument("--scope", choices=("first_wave", "interface"), default="first_wave")
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--restore-installed", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.restore_installed:
        if args.render_only or args.install:
            raise SystemExit("ERROR: --restore-installed cannot be combined with build options")
        restore_installed()
        return
    if args.render_only and args.install:
        raise SystemExit("ERROR: --render-only cannot be combined with --install")
    if args.install and game_is_running():
        raise SystemExit("ERROR: the game is running; no backups or UI archives were changed")

    font_path = args.font if args.font.is_absolute() else ROOT / args.font
    if not font_path.is_file():
        raise SystemExit(f"ERROR: Cyrillic font not found: {font_path}")
    if not SANS_FONT_PATH.is_file():
        raise SystemExit(f"ERROR: Cyrillic sans-serif font not found: {SANS_FONT_PATH}")
    config = load_asset_source()
    rows = scope_rows(config, args.scope)
    sources = {
        name: select_source(spec, require_backup=args.install)
        for name, spec in ARCHIVE_SPECS.items()
    }

    rendered = []
    for archive, spec in ARCHIVE_SPECS.items():
        pak = Pak(sources[archive])
        for row in rows:
            if row["archive"] == archive:
                rendered.append(render_asset(pak, row, config, font_path))
    rendered = tuple(rendered)
    contacts = write_previews(rendered, IMAGE_DIR, font_path)
    if args.render_only:
        print(json.dumps({"rendered": len(rendered), "image_dir": str(IMAGE_DIR), "contact_sheets": contacts}, ensure_ascii=False, indent=2))
        return

    archives = []
    output_hashes = {}
    for archive, spec in ARCHIVE_SPECS.items():
        archive_rendered = tuple(item for item in rendered if item.archive == archive)
        result = build_archive(spec, sources[archive], archive_rendered)
        archives.append(result)
        output_hashes[archive] = result["output_sha256"].removeprefix("sha256:")

    receipt = {
        "schema_version": 1,
        "build_mode": f"luca_baked_ui_images_{args.scope}",
        "scope": args.scope,
        "canonical_source": str(ASSET_SOURCE),
        "canonical_source_sha256": "sha256:" + digest_file(ASSET_SOURCE),
        "canonical_status": config["status"],
        "font": str(font_path),
        "rendered_image_directory": str(IMAGE_DIR),
        "contact_sheets": list(contacts),
        "archives": archives,
    }
    if args.install:
        receipt["installed_sha256"] = {
            name: "sha256:" + digest
            for name, digest in install_artifacts(output_hashes).items()
        }
    RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


ASSET_CONFIG = load_asset_source()
FIRST_WAVE_ROWS = first_wave_rows(ASSET_CONFIG)
INTERFACE_ROWS = scope_rows(ASSET_CONFIG, "interface")


if __name__ == "__main__":
    main()
