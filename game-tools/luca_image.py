"""Decode LUCA/RealLive CZ0-CZ3 images and write lossless CZ0 images.

The CZ1-CZ3 decoder is ported from GARbro's ImageCZ.cs:
Copyright (C) 2019 by morkt, distributed under the MIT License.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class CzImage:
    version: int
    width: int
    height: int
    bpp: int
    pixels: bytes
    offset_x: int = 0
    offset_y: int = 0
    canvas_width: int | None = None
    canvas_height: int | None = None

    def __post_init__(self):
        expected = self.width * self.height * self.bpp // 8
        if self.bpp not in (8, 32):
            raise ValueError(f"unsupported CZ bits per pixel: {self.bpp}")
        if len(self.pixels) != expected:
            raise ValueError(f"CZ pixel size mismatch: expected {expected}, got {len(self.pixels)}")


def _read_metadata(data: bytes):
    if len(data) < 0x10 or data[:2] != b"CZ" or data[3] != 0:
        raise ValueError("not a CZ image")
    version_byte = data[2]
    if version_byte not in b"0123":
        raise ValueError(f"unsupported CZ version byte: {version_byte:#x}")
    version = version_byte - ord("0")
    header_length, width, height, bpp, reserved = struct.unpack_from("<IHHHH", data, 4)
    if not 0x10 <= header_length <= len(data):
        raise ValueError(f"invalid CZ header length: {header_length}")
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid CZ dimensions: {width}x{height}")
    if bpp not in (8, 32):
        raise ValueError(f"unsupported CZ bits per pixel: {bpp}")
    if reserved != 4:
        raise ValueError(f"unexpected CZ reserved value: {reserved}")
    offset_x = offset_y = 0
    canvas_width = width
    canvas_height = height
    if header_length >= 0x1C:
        offset_x, offset_y, canvas_width, canvas_height = struct.unpack_from("<hhHH", data, 0x10)
        if canvas_width <= 0 or canvas_height <= 0:
            raise ValueError(f"invalid CZ canvas dimensions: {canvas_width}x{canvas_height}")
    return version, header_length, width, height, bpp, offset_x, offset_y, canvas_width, canvas_height


def _range_offset(part: bytes, source: int):
    if source < 0 or source + 1 >= len(part):
        raise ValueError(f"CZ back-reference is out of bounds: {source}")
    return ((part[source] | part[source + 1] << 8) - 0x101) * 2


def _decode_part(part: bytes, expected_size: int):
    if len(part) % 2:
        raise ValueError("CZ compressed part has odd length")
    cache: dict[int, bytes] = {}
    one_cache: dict[int, int] = {}
    active_ranges: set[int] = set()

    def copy_one(source: int):
        if source in one_cache:
            return one_cache[source]
        path = []
        visited = set()
        current = source
        while True:
            if current in one_cache:
                value = one_cache[current]
                break
            if current in visited:
                raise ValueError("cyclic CZ single-byte back-reference")
            if current < 0 or current + 1 >= len(part):
                raise ValueError(f"CZ single-byte reference is out of bounds: {current}")
            visited.add(current)
            path.append(current)
            if part[current + 1] == 0:
                value = part[current]
                break
            target = _range_offset(part, current)
            if target == current:
                value = 0
                break
            current = target
        for item in path:
            one_cache[item] = value
        return value

    def copy_range(source: int):
        if source in cache:
            return cache[source]
        if source in active_ranges:
            raise ValueError("cyclic CZ range back-reference")
        if source < 0 or source + 3 >= len(part):
            raise ValueError(f"CZ range reference is out of bounds: {source}")
        active_ranges.add(source)
        output = bytearray()
        if part[source + 1] == 0:
            output.append(part[source])
        else:
            target = _range_offset(part, source)
            if target == source:
                output.append(0)
            else:
                output.extend(copy_range(target))
        first = output[0]
        second = source + 2
        if part[second + 1] == 0:
            output.append(part[second])
        else:
            target = _range_offset(part, second)
            output.append(first if target == source else copy_one(target))
        active_ranges.remove(source)
        result = bytes(output)
        cache[source] = result
        return result

    output = bytearray()
    for source in range(0, len(part), 2):
        if part[source + 1] == 0:
            output.append(part[source])
        else:
            output.extend(copy_range(_range_offset(part, source)))
        if len(output) > expected_size:
            raise ValueError("CZ part expands beyond declared size")
    if len(output) != expected_size:
        raise ValueError(f"CZ part size mismatch: expected {expected_size}, got {len(output)}")
    return bytes(output)


def _decode_cz1_payload(data: bytes, offset: int, expected_total: int):
    if offset + 4 > len(data):
        raise ValueError("CZ part table is truncated")
    part_count = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    if not 0 < part_count <= 100_000:
        raise ValueError(f"invalid CZ part count: {part_count}")
    parts = []
    for _ in range(part_count):
        if offset + 8 > len(data):
            raise ValueError("CZ part table is truncated")
        word_count, unpacked_size = struct.unpack_from("<II", data, offset)
        offset += 8
        packed_size = word_count * 2
        parts.append((packed_size, unpacked_size))
    output = bytearray()
    for packed_size, unpacked_size in parts:
        end = offset + packed_size
        if end > len(data):
            raise ValueError("CZ compressed part is truncated")
        output.extend(_decode_part(data[offset:end], unpacked_size))
        offset = end
    if len(output) != expected_total:
        raise ValueError(f"CZ output size mismatch: expected {expected_total}, got {len(output)}")
    if offset != len(data):
        raise ValueError(f"unexpected trailing CZ data: {len(data) - offset} bytes")
    return output


def decode_cz(data: bytes):
    (
        version,
        header_length,
        width,
        height,
        bpp,
        offset_x,
        offset_y,
        canvas_width,
        canvas_height,
    ) = _read_metadata(data)
    expected_size = width * height * bpp // 8
    if version == 0:
        end = header_length + expected_size
        if end != len(data):
            raise ValueError(f"CZ0 payload size mismatch: expected file size {end}, got {len(data)}")
        pixels = bytearray(data[header_length:end])
    else:
        pixels = _decode_cz1_payload(data, header_length, expected_size)
        if version == 2:
            if len(pixels) % 4:
                raise ValueError("CZ2 output is not uint32-aligned")
            values = list(struct.unpack(f"<{len(pixels) // 4}I", pixels))
            stride = width * bpp // 8 // 4
            third = (height + 2) // 3
            for y in range(height):
                destination = width * y
                if y % third != 0:
                    for x in range(stride):
                        index = destination + x
                        values[index] = (values[index] + values[index - stride]) & 0xFFFFFFFF
            pixels = bytearray(struct.pack(f"<{len(values)}I", *values))
        elif version == 3:
            stride = width * bpp // 8
            third = (height + 2) // 3
            for y in range(height):
                destination = y * stride
                if y % third != 0:
                    previous = destination - stride
                    for x in range(stride):
                        pixels[destination + x] = (pixels[destination + x] + pixels[previous + x]) & 0xFF
    return CzImage(
        version=version,
        width=width,
        height=height,
        bpp=bpp,
        pixels=bytes(pixels),
        offset_x=offset_x,
        offset_y=offset_y,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
    )


def encode_cz0(image: CzImage):
    header_length = 0x40
    canvas_width = image.canvas_width or image.width
    canvas_height = image.canvas_height or image.height
    header = bytearray(header_length)
    struct.pack_into(
        "<4sIHHHHhhHHHH",
        header,
        0,
        b"CZ0\0",
        header_length,
        image.width,
        image.height,
        image.bpp,
        4,
        image.offset_x,
        image.offset_y,
        canvas_width,
        canvas_height,
        image.width,
        image.height,
    )
    return bytes(header) + image.pixels
