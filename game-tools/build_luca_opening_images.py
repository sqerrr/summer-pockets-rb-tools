"""Build and optionally install the approved Russian opening intertitles."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from luca import Pak
from luca_image import CzImage, decode_cz, encode_cz0


ROOT = Path(__file__).resolve().parents[1]
INSTALLED_PAK = ROOT / "Summer Pockets REFLECTION BLUE_Steam/files/image/OTHCG.PAK"
PRISTINE_BACKUP = ROOT / "build/steam/OTHCG.pristine.PAK"
OUTPUT_PAK = ROOT / "build/steam/OTHCG.russian-opening.PAK"
RECEIPT_PATH = ROOT / "build/steam/opening-images-receipt.json"
IMAGE_DIR = ROOT / "build/steam/opening-russian-images"
CONTACT_SHEET = ROOT / "build/steam/opening-russian-contact-sheet.png"
TITLE_SOURCE = ROOT / "translation/ui/opening-titles.json"


def load_title_source(path: Path = TITLE_SOURCE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported opening-title source schema")
    if data.get("archive") != "OTHCG.PAK":
        raise ValueError("opening titles must target OTHCG.PAK")
    if data.get("status") != "approved" or data.get("approved_by") != "user":
        raise ValueError("opening-title source is not explicitly user-approved")
    source_hash = str(data.get("pristine_sha256", ""))
    if not source_hash.startswith("sha256:") or len(source_hash) != 71:
        raise ValueError("invalid pristine OTHCG.PAK hash")

    render = data.get("render")
    if not isinstance(render, dict) or render.get("long_line_policy") != "horizontal_scale_only":
        raise ValueError("unsupported opening-title render profile")
    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) != 17:
        raise ValueError("opening-title source must contain exactly 17 entries")
    entry_ids = set()
    for index, row in enumerate(entries):
        expected_name = f"EF_CHARACTER01_{index:02d}en"
        if not isinstance(row, dict) or row.get("entry_name") != expected_name:
            raise ValueError(f"unexpected opening-title entry at position {index}")
        entry_id = row.get("entry_id")
        if not isinstance(entry_id, int) or entry_id in entry_ids:
            raise ValueError(f"invalid or duplicate opening-title entry ID: {entry_id}")
        entry_ids.add(entry_id)
        if not isinstance(row.get("text_ru"), str) or not row["text_ru"].strip():
            raise ValueError(f"empty Russian opening title: {expected_name}")
    return data


TITLE_CONFIG = load_title_source()
RENDER_CONFIG = TITLE_CONFIG["render"]
SOURCE_SHA256 = TITLE_CONFIG["pristine_sha256"].removeprefix("sha256:")
FONT_PATH = Path(RENDER_CONFIG["font_path"])
CANVAS_SIZE = tuple(RENDER_CONFIG["canvas_size"])
TEXT_CENTER = tuple(RENDER_CONFIG["text_center"])
FONT_SIZE = RENDER_CONFIG["font_size"]
MAX_TEXT_WIDTH = RENDER_CONFIG["max_text_width"]
HALO_WIDTH = RENDER_CONFIG["halo_width"]
INNER_STROKE_WIDTH = RENDER_CONFIG["inner_stroke_width"]
GLOW_COLOR = tuple(RENDER_CONFIG["glow_color"])
FILL_COLOR = tuple(RENDER_CONFIG["fill_color"])
INNER_STROKE_COLOR = tuple(RENDER_CONFIG["inner_stroke_color"])
FAR_GLOW_RADIUS = RENDER_CONFIG["far_glow_radius"]
FAR_GLOW_ALPHA = RENDER_CONFIG["far_glow_alpha"]
NEAR_GLOW_RADIUS = RENDER_CONFIG["near_glow_radius"]
NEAR_GLOW_ALPHA = RENDER_CONFIG["near_glow_alpha"]
TITLE_ROWS = tuple(TITLE_CONFIG["entries"])


@dataclass(frozen=True)
class RenderedTitle:
    name: str
    entry_id: int
    text: str
    image: Image.Image
    natural_width: int
    compression: float
    alpha_bbox: tuple[int, int, int, int]


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def default_source() -> Path:
    return PRISTINE_BACKUP if PRISTINE_BACKUP.exists() else INSTALLED_PAK


def assert_pristine(path: Path) -> str:
    actual = digest_file(path)
    if actual != SOURCE_SHA256:
        raise SystemExit(
            f"ОШИБКА: неверный pristine OTHCG.PAK: ожидался {SOURCE_SHA256}, получен {actual}"
        )
    return actual


def game_is_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SummerPocketsRB.exe", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return "SummerPocketsRB.exe" in result.stdout


def _scaled_alpha(alpha: Image.Image, factor: float) -> Image.Image:
    return alpha.point(lambda value: min(255, round(value * factor)))


def render_title(text: str, font_path: Path = FONT_PATH) -> tuple[Image.Image, int, float]:
    font = ImageFont.truetype(str(font_path), FONT_SIZE)
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = measure.textbbox((0, 0), text, font=font, stroke_width=HALO_WIDTH)
    natural_width = bbox[2] - bbox[0]
    natural_height = bbox[3] - bbox[1]
    padding = 40
    patch_size = (natural_width + padding * 2, natural_height + padding * 2)
    origin = (padding - bbox[0], padding - bbox[1])

    mask = Image.new("L", patch_size, 0)
    ImageDraw.Draw(mask).text(origin, text, font=font, fill=255)
    far_glow = _scaled_alpha(mask.filter(ImageFilter.GaussianBlur(FAR_GLOW_RADIUS)), FAR_GLOW_ALPHA)
    near_glow = _scaled_alpha(mask.filter(ImageFilter.GaussianBlur(NEAR_GLOW_RADIUS)), NEAR_GLOW_ALPHA)

    patch = Image.new("RGBA", patch_size, (255, 255, 255, 0))
    for glow in (far_glow, near_glow):
        layer = Image.new("RGBA", patch_size, GLOW_COLOR + (0,))
        layer.putalpha(glow)
        patch = Image.alpha_composite(patch, layer)
    draw = ImageDraw.Draw(patch)
    draw.text(
        origin,
        text,
        font=font,
        fill=GLOW_COLOR + (255,),
        stroke_width=HALO_WIDTH,
        stroke_fill=GLOW_COLOR + (255,),
    )
    draw.text(
        origin,
        text,
        font=font,
        fill=FILL_COLOR + (255,),
        stroke_width=INNER_STROKE_WIDTH,
        stroke_fill=INNER_STROKE_COLOR + (255,),
    )

    compression = min(1.0, MAX_TEXT_WIDTH / natural_width)
    if compression < 1.0:
        patch = patch.resize(
            (round(patch.width * compression), patch.height),
            Image.Resampling.LANCZOS,
        )

    visible = patch.getchannel("A").point(lambda value: 255 if value >= 2 else 0).getbbox()
    if visible is None:
        raise ValueError("rendered title is empty")
    patch = patch.crop(visible)
    canvas = Image.new("RGBA", CANVAS_SIZE, (255, 255, 255, 0))
    x = round(TEXT_CENTER[0] - patch.width / 2)
    y = round(TEXT_CENTER[1] - patch.height / 2)
    canvas.alpha_composite(patch, (x, y))
    return canvas, natural_width, compression


def render_all(font_path: Path = FONT_PATH) -> list[RenderedTitle]:
    rendered = []
    for row in TITLE_ROWS:
        name = row["entry_name"]
        entry_id = row["entry_id"]
        text = row["text_ru"]
        image, natural_width, compression = render_title(text, font_path)
        alpha_bbox = image.getchannel("A").getbbox()
        if alpha_bbox is None:
            raise ValueError(f"rendered title is empty: {name}")
        rendered.append(
            RenderedTitle(name, entry_id, text, image, natural_width, compression, alpha_bbox)
        )
    return rendered


def write_rendered_images(rendered: list[RenderedTitle], image_dir: Path, contact_sheet: Path) -> None:
    image_dir.mkdir(parents=True, exist_ok=True)
    for title in rendered:
        title.image.save(image_dir / f"{title.name}.png")

    cell_width, cell_height = 480, 300
    columns = 4
    rows = (len(rendered) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (30, 38, 51))
    draw = ImageDraw.Draw(sheet)
    for index, title in enumerate(rendered):
        thumbnail = Image.new("RGBA", CANVAS_SIZE, (30, 38, 51, 255))
        thumbnail.alpha_composite(title.image)
        thumbnail.thumbnail((cell_width, 270), Image.Resampling.LANCZOS)
        x = index % columns * cell_width
        y = index // columns * cell_height
        sheet.paste(thumbnail.convert("RGB"), (x, y))
        draw.text((x + 8, y + 274), title.name, fill=(235, 238, 243))
    contact_sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(contact_sheet)


def encode_replacements(source: Pak, rendered: list[RenderedTitle]):
    replacements = {}
    details = []
    for title in rendered:
        matches = [entry for entry in source.entries if entry.name == title.name]
        if len(matches) != 1:
            raise ValueError(f"expected one PAK entry named {title.name}, got {len(matches)}")
        entry = matches[0]
        if entry.entry_id != title.entry_id:
            raise ValueError(
                f"unexpected PAK entry ID for {title.name}: "
                f"expected {title.entry_id}, got {entry.entry_id}"
            )
        original = decode_cz(source.read_entry(entry))
        if (original.width, original.height) != CANVAS_SIZE or original.bpp != 32:
            raise ValueError(
                f"unexpected image geometry for {title.name}: "
                f"{original.width}x{original.height} {original.bpp}bpp"
            )
        replacement = encode_cz0(
            CzImage(
                version=0,
                width=original.width,
                height=original.height,
                bpp=original.bpp,
                pixels=title.image.tobytes(),
                offset_x=original.offset_x,
                offset_y=original.offset_y,
                canvas_width=original.canvas_width,
                canvas_height=original.canvas_height,
            )
        )
        replacements[entry] = replacement
        details.append({
            "name": title.name,
            "index": entry.index,
            "entry_id": entry.entry_id,
            "text": title.text,
            "original_codec": f"CZ{original.version}",
            "original_size": entry.size,
            "replacement_size": len(replacement),
            "natural_width": title.natural_width,
            "horizontal_scale": round(title.compression, 6),
            "alpha_bbox": list(title.alpha_bbox),
        })
    return replacements, details


def validate_built(source: Pak, built: Pak, replacements: dict) -> None:
    source_layout = [(entry.entry_id, entry.name) for entry in source.entries]
    built_layout = [(entry.entry_id, entry.name) for entry in built.entries]
    if source_layout != built_layout:
        raise ValueError("OTHCG.PAK entry IDs, names, or order changed")
    for source_entry, expected in replacements.items():
        actual = built.read_entry(source_entry.index)
        if actual != expected:
            raise ValueError(f"PAK read-back bytes differ: {source_entry.name}")
        decoded = decode_cz(actual)
        if decoded.version != 0 or decoded.pixels != expected[0x40:]:
            raise ValueError(f"CZ0 pixel read-back differs: {source_entry.name}")


def install_opening_images(output_path: Path, source_path: Path) -> str:
    if game_is_running():
        raise SystemExit("ОШИБКА: игра запущена; русский OTHCG.PAK не установлен")
    if not PRISTINE_BACKUP.exists():
        if source_path != INSTALLED_PAK:
            raise SystemExit("ОШИБКА: pristine backup отсутствует, а source не является установленным PAK")
        shutil.copy2(source_path, PRISTINE_BACKUP)
        assert_pristine(PRISTINE_BACKUP)
    else:
        assert_pristine(PRISTINE_BACKUP)
    shutil.copy2(output_path, INSTALLED_PAK)
    installed_hash = digest_file(INSTALLED_PAK)
    output_hash = digest_file(output_path)
    if installed_hash != output_hash:
        raise SystemExit("ОШИБКА: установленный OTHCG.PAK не совпал с артефактом")
    return installed_hash


def restore_installed() -> None:
    if game_is_running():
        raise SystemExit("ОШИБКА: игра запущена; pristine OTHCG.PAK не восстановлен")
    assert_pristine(PRISTINE_BACKUP)
    shutil.copy2(PRISTINE_BACKUP, INSTALLED_PAK)
    assert_pristine(INSTALLED_PAK)
    print(f"Restored pristine OTHCG.PAK: sha256:{SOURCE_SHA256}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT_PAK)
    parser.add_argument("--receipt", type=Path, default=RECEIPT_PATH)
    parser.add_argument("--image-dir", type=Path, default=IMAGE_DIR)
    parser.add_argument("--contact-sheet", type=Path, default=CONTACT_SHEET)
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--restore-installed", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.restore_installed:
        restore_installed()
        return
    if args.render_only and args.install:
        raise SystemExit("ОШИБКА: --render-only несовместим с --install")

    font_path = resolve(FONT_PATH)
    if not font_path.is_file():
        raise SystemExit(f"ОШИБКА: шрифт не найден: {font_path}")
    image_dir = resolve(args.image_dir)
    contact_sheet = resolve(args.contact_sheet)
    rendered = render_all(font_path)
    write_rendered_images(rendered, image_dir, contact_sheet)
    if args.render_only:
        print(f"Rendered {len(rendered)} approved opening titles to {image_dir}")
        print(f"Contact sheet: {contact_sheet}")
        return

    source_path = resolve(args.source) if args.source else default_source()
    source_hash = assert_pristine(source_path)
    output_path = resolve(args.output)
    receipt_path = resolve(args.receipt)
    source = Pak(source_path)
    replacements, details = encode_replacements(source, rendered)
    source.build(output_path, replacements)
    built = Pak(output_path)
    validate_built(source, built, replacements)
    output_hash = digest_file(output_path)

    receipt = {
        "build_mode": "opening_images",
        "title_source": str(TITLE_SOURCE),
        "title_source_sha256": "sha256:" + digest_file(TITLE_SOURCE),
        "approval_status": TITLE_CONFIG["status"],
        "approved_by": TITLE_CONFIG["approved_by"],
        "approved_date": TITLE_CONFIG["approved_date"],
        "source": str(source_path),
        "source_sha256": "sha256:" + source_hash,
        "output": str(output_path),
        "output_sha256": "sha256:" + output_hash,
        "entry_count": built.entry_count,
        "replacement_count": len(replacements),
        "codec": "CZ0 RGBA",
        "font": str(font_path),
        "render": RENDER_CONFIG,
        "entries": details,
    }
    if args.install:
        receipt["installed_sha256"] = "sha256:" + install_opening_images(output_path, source_path)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
