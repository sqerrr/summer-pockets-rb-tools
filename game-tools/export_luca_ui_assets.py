"""Export a diagnostic catalogue of active Steam/LUCA interface images."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont

from luca import Pak
from luca_image import decode_cz, read_cz_metadata, rgba_pixels


ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = ROOT / "Summer Pockets REFLECTION BLUE_Steam/files/image"
OUTPUT_ROOT = ROOT / "build/steam/ui-assets"
ARCHIVES = ("SYSCG.PAK", "PARTS.PAK", "MANUAL.PAK", "MANUAL_DECK.PAK", "SYSCG2.PAK", "OTHCG.PAK")
OTHCG_PREFIXES = ("__SYS_KM_", "__SYS_LOGO", "__SYS_RBLOGO", "__SYS_RC_", "__SYS_TM_", "__SYS_TW_")


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def selected_entry(archive: str, name: str | None) -> bool:
    if not name:
        return False
    if archive != "OTHCG.PAK":
        return True
    return name.startswith(OTHCG_PREFIXES)


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "unnamed"


def checkerboard(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGBA", size, (42, 48, 60, 255))
    draw = ImageDraw.Draw(image)
    tile = 16
    for y in range(0, size[1], tile):
        for x in range(0, size[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(62, 70, 84, 255))
    return image


def render_thumbnail(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = image.copy()
    image.thumbnail(size, Image.Resampling.LANCZOS)
    background = checkerboard(size)
    x = (size[0] - image.width) // 2
    y = (size[1] - image.height) // 2
    background.alpha_composite(image, (x, y))
    return background.convert("RGB")


def write_contact_sheets(rows: list[dict], thumbnails: dict[int, Image.Image], output: Path) -> list[str]:
    cell_width, cell_height = 360, 245
    image_width, image_height = 344, 190
    columns, page_size = 4, 48
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13)
    paths = []
    for page_start in range(0, len(rows), page_size):
        page = rows[page_start:page_start + page_size]
        page_rows = (len(page) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_width, page_rows * cell_height), (24, 28, 36))
        draw = ImageDraw.Draw(sheet)
        for local_index, row in enumerate(page):
            x = local_index % columns * cell_width
            y = local_index // columns * cell_height
            thumb = thumbnails.get(row["index"])
            if thumb is None:
                thumb = Image.new("RGB", (image_width, image_height), (65, 42, 48))
                warning = row.get("error") or row.get("format", "unsupported")
                ImageDraw.Draw(thumb).multiline_text((10, 10), warning[:160], font=font, fill=(255, 210, 210), spacing=4)
            sheet.paste(thumb, (x + 8, y + 8))
            label = (
                f'{row["index"]} / {row["entry_id"]}  {row["name"]}\n'
                f'{row.get("format", "non-CZ")}  {row.get("width", "?")}x{row.get("height", "?")} '
                f'{row.get("bpp", "?")}bpp'
            )
            draw.multiline_text((x + 8, y + 202), label, font=font, fill=(235, 238, 244), spacing=2)
        page_number = page_start // page_size + 1
        path = output / f"contact-{page_number:02d}.png"
        sheet.save(path)
        paths.append(str(path))
    return paths


def export_archive(path: Path, output_root: Path) -> dict:
    pak = Pak(path)
    archive_output = output_root / path.stem
    image_output = archive_output / "images"
    image_output.mkdir(parents=True, exist_ok=True)
    rows = []
    thumbnails = {}
    decoded_count = 0
    unsupported_count = 0

    for entry in pak.entries:
        if not selected_entry(path.name, entry.name):
            continue
        payload = pak.read_entry(entry)
        row = {
            "archive": path.name,
            "index": entry.index,
            "entry_id": entry.entry_id,
            "name": entry.name,
            "offset": entry.offset,
            "size": entry.size,
            "payload_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        }
        if payload[:2] == b"CZ":
            try:
                metadata = read_cz_metadata(payload)
                row.update({
                    "format": f"CZ{metadata.version}",
                    "header_length": metadata.header_length,
                    "width": metadata.width,
                    "height": metadata.height,
                    "bpp": metadata.bpp,
                    "offset_x": metadata.offset_x,
                    "offset_y": metadata.offset_y,
                    "canvas_width": metadata.canvas_width,
                    "canvas_height": metadata.canvas_height,
                })
                decoded = decode_cz(payload)
                image = Image.frombytes("RGBA", (decoded.width, decoded.height), rgba_pixels(decoded))
                png_path = image_output / f"{entry.index:04d}-{safe_name(entry.name or '')}.png"
                image.save(png_path)
                row["png"] = str(png_path)
                thumbnails[entry.index] = render_thumbnail(image, (344, 190))
                decoded_count += 1
            except ValueError as error:
                row["error"] = str(error)
                unsupported_count += 1
        else:
            row["format"] = payload[:4].decode("ascii", errors="replace").rstrip("\0") or "binary"
            row["error"] = "not a CZ image"
            unsupported_count += 1
        rows.append(row)

    catalog_path = archive_output / "catalog.jsonl"
    catalog_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    sheets = write_contact_sheets(rows, thumbnails, archive_output)
    return {
        "archive": str(path),
        "archive_sha256": "sha256:" + digest_file(path),
        "entry_count": pak.entry_count,
        "selected_count": len(rows),
        "decoded_count": decoded_count,
        "unsupported_count": unsupported_count,
        "catalog": str(catalog_path),
        "contact_sheets": sheets,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    summaries = [export_archive(IMAGE_ROOT / name, output) for name in ARCHIVES]
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest), "archives": summaries}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
