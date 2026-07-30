"""Read and safely rebuild LUCA System PAK archives and scripts."""

from dataclasses import dataclass
from pathlib import Path
import re
import struct


OPCODES = (
    "EQU", "EQUN", "EQUV", "ADD", "SUB", "MUL", "DIV", "MOD", "AND",
    "OR", "RANDOM", "VARSTR", "SET", "FLAGCLR", "GOTO", "ONGOTO",
    "GOSUB", "IFY", "IFN", "RETURN", "JUMP", "FARCALL", "FARRETURN",
    "JUMPPOINT", "END", "VARSTR_SET", "TALKNAME_SET", "ARFLAGSET",
    "COLORBG_SET", "SPLINE_SET", "SHAKELIST_SET", "MESSAGE",
    "MESSAGE_CLEAR", "SELECT", "CLOSE_WINDOW", "LOG", "LOG_PAUSE",
    "LOG_END", "VOICE", "WAIT_COUNT", "WAIT_TIME", "FFSTOP", "INIT",
    "STOP", "IMAGELOAD", "IMAGEUPADTE", "ARC", "MOVE", "MOVE2", "ROT",
    "PEND", "FADE", "SCALE", "SHAKE", "SHAKELIST", "BASE", "MCMOVE",
    "MCARC", "MCROT", "MCSHAKE", "MCFADE", "WAIT", "DRAW", "WIPE",
    "FRAMEON", "FRAMEOFF", "FW", "SCISSOR", "DELAY", "RASTER", "TONE",
    "SCALECOSSIN", "BMODE", "SIZE", "SPLINE", "DISP", "MASK",
    "SG_QUAKE", "BGM", "BGM_WAITSTART", "BGM_WAITFADE", "SE", "SE_STOP",
    "SE_WAIT", "VOLUME", "MOVIE", "SETCGFLAG", "EX", "TROPHY",
    "SETBGMFLAG", "TASK", "BTFUNC", "BATTLE", "KOEP",
    "BT_ACCESSORY_SELECT", "UNDO_CLEAR", "PTFUNC", "PT", "GMFUNC", "GM",
    "DEL_CALLSTACK", "FULLQUAKE_ZOOM", "LBFUNC", "LBBG", "HAIKEI_SET",
    "SAYAVOICETEXT", "UNKNOWN",
)

# These numeric layouts were verified against the 2025 Steam script archive.
# The mnemonic table above comes from an older LUCA version and is diagnostic
# only; build logic must use numeric opcodes.
LOCAL_TARGET_OPCODES = frozenset((15, 17, 18, 19))
CROSS_TARGET_OPCODES = frozenset((21, 22))
TARGET_OPCODES = LOCAL_TARGET_OPCODES | CROSS_TARGET_OPCODES
LZW_MAGIC = b"LZW\0"
SOURCE_LANGUAGES = ("ja", "en", "zh-Hans")
TEXT_RECORD_LAYOUTS = {
    36: {
        "flag": 3,
        "fixed_count": 2,
        "prefix_size": 2,
        "encodings": ("utf-16le", "utf-8", "utf-16le"),
        "tail_sizes": frozenset((1, 5)),
    },
    40: {
        "flag": 1,
        "fixed_count": 1,
        "prefix_size": 8,
        "encodings": ("utf-16le", "utf-16le", "utf-16le"),
        "tail_sizes": frozenset((4,)),
    },
}


@dataclass(frozen=True)
class PakEntry:
    index: int
    entry_id: int
    name: str | None
    offset: int
    size: int


@dataclass(frozen=True)
class ScriptRecord:
    offset: int
    length: int
    opcode: int
    name: str
    flag: int
    fixed_params: tuple[int, ...]
    params: bytes


@dataclass(frozen=True)
class LucaString:
    text: str
    encoding: str
    offset: int
    data_offset: int
    data_size: int
    end_offset: int


@dataclass(frozen=True)
class ClassifiedSourceRecord:
    classification: str
    layout: str | None = None
    prefix: bytes = b""
    strings: tuple[LucaString, ...] = ()
    tail: bytes = b""
    error: str | None = None


@dataclass(frozen=True)
class ScriptRelocation:
    replacements: dict[int, bytes]
    offset_maps: dict[int, dict[int, int]]
    record_count: int
    reference_count: int
    label_count: int


class Pak:
    """Minimal read-only implementation of the LUCA PAK index."""

    def __init__(self, path):
        self.path = Path(path)
        self.file_size = self.path.stat().st_size
        with self.path.open("rb") as fh:
            header = fh.read(36)
            if len(header) != 36:
                raise ValueError("PAK header is truncated")
            (
                self.data_offset,
                self.entry_count,
                self.id_start,
                self.block_size,
                self.subdir_offset,
                self.unknown2,
                self.unknown3,
                self.unknown4,
                self.flags,
            ) = struct.unpack("<9I", header)

            if not 0 < self.entry_count <= 100_000:
                raise ValueError(f"invalid PAK entry count: {self.entry_count}")
            if not 0 < self.block_size <= 0x10000:
                raise ValueError(f"invalid PAK block size: {self.block_size}")
            if not 36 < self.data_offset <= self.file_size:
                raise ValueError(f"invalid PAK data offset: {self.data_offset}")

            extra_counts = {0: 1, 1: 2, 2: 4, 3: 5, 4: 7}
            extra_count = extra_counts.get(self.flags & 7, 0)
            fh.seek(extra_count * 4, 1)

            self.index_offset = fh.tell()

            raw_index = fh.read(self.entry_count * 8)
            if len(raw_index) != self.entry_count * 8:
                raise ValueError("PAK entry index is truncated")
            locations = [
                struct.unpack_from("<II", raw_index, i * 8)
                for i in range(self.entry_count)
            ]

            if self.flags & 0x100:
                fh.seek(self.entry_count * 12, 1)

            names = [None] * self.entry_count
            if self.flags & 0x200:
                if self.subdir_offset:
                    self.subdirectory = self._read_cstring(fh)
                else:
                    self.subdirectory = None
                names = [self._read_cstring(fh) for _ in range(self.entry_count)]
            else:
                self.subdirectory = None

        entries = []
        for index, ((block_offset, size), name) in enumerate(zip(locations, names)):
            offset = block_offset * self.block_size
            if size and (offset < self.data_offset or offset + size > self.file_size):
                raise ValueError(
                    f"PAK entry {index} is out of bounds: offset={offset} size={size}"
                )
            entries.append(PakEntry(index, self.id_start + index, name, offset, size))
        self.entries = tuple(entries)

    @staticmethod
    def _read_cstring(fh):
        data = bytearray()
        while True:
            byte = fh.read(1)
            if not byte:
                raise ValueError("unterminated PAK string")
            if byte == b"\0":
                return data.decode("utf-8")
            data.extend(byte)

    def read_entry(self, entry):
        if isinstance(entry, int):
            entry = self.entries[entry]
        with self.path.open("rb") as fh:
            fh.seek(entry.offset)
            data = fh.read(entry.size)
        if len(data) != entry.size:
            raise ValueError(f"PAK entry {entry.index} is truncated")
        return data

    def build(self, output_path, replacements=None):
        """Write a PAK, preserving bytes exactly when entry sizes do not change."""
        output_path = Path(output_path)
        replacements = replacements or {}
        replacement_data = {
            (key.index if isinstance(key, PakEntry) else int(key)): value
            for key, value in replacements.items()
        }
        for index in replacement_data:
            if not 0 <= index < self.entry_count:
                raise IndexError(f"PAK entry index out of range: {index}")

        same_sizes = all(
            len(data) == self.entries[index].size
            for index, data in replacement_data.items()
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if same_sizes:
            archive = bytearray(self.path.read_bytes())
            for index, data in replacement_data.items():
                entry = self.entries[index]
                archive[entry.offset:entry.offset + entry.size] = data
            output_path.write_bytes(archive)
            return

        prefix = bytearray(self.path.read_bytes()[:self.data_offset])
        offset = self.data_offset
        chunks = []
        for entry in self.entries:
            data = replacement_data.get(entry.index)
            if data is None:
                data = self.read_entry(entry)
            if data:
                block_offset = offset // self.block_size
                if block_offset * self.block_size != offset:
                    raise ValueError("PAK data offset lost block alignment")
            else:
                block_offset = 0
            struct.pack_into(
                "<II", prefix, self.index_offset + entry.index * 8,
                block_offset, len(data),
            )
            chunks.append(data)
            if data:
                offset += len(data)
                offset += (-offset) % self.block_size

        with output_path.open("wb") as fh:
            fh.write(prefix)
            for data in chunks:
                if not data:
                    continue
                fh.write(data)
                padding = (-fh.tell()) % self.block_size
                if padding:
                    fh.write(b"\0" * padding)


def iter_script_records(data):
    """Yield aligned LUCA bytecode records through the data boundary."""
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError(f"truncated script record header at {offset:#x}")
        length, opcode, flag = struct.unpack_from("<HBB", data, offset)
        if length < 4 or offset + length > len(data):
            raise ValueError(
                f"invalid script record length {length} at {offset:#x}"
            )
        raw = data[offset + 4:offset + length]
        fixed_count = 0 if flag == 0 else 1 if flag == 1 else 2
        fixed_size = fixed_count * 2
        if fixed_size > len(raw):
            raise ValueError(f"truncated fixed parameters at {offset:#x}")
        fixed_params = struct.unpack_from(f"<{fixed_count}H", raw) if fixed_count else ()
        name = OPCODES[opcode] if opcode < len(OPCODES) else f"OP_{opcode:02X}"
        yield ScriptRecord(
            offset=offset,
            length=length,
            opcode=opcode,
            name=name,
            flag=flag,
            fixed_params=fixed_params,
            params=raw[fixed_size:],
        )
        offset += (length + 1) & ~1


def read_utf16z(data, offset=0):
    """Decode one little-endian UTF-16 NUL-terminated string."""
    end = offset
    while end + 1 < len(data):
        if data[end:end + 2] == b"\0\0":
            return data[offset:end].decode("utf-16le"), end + 2
        end += 2
    raise ValueError("unterminated UTF-16LE string")


def read_luca_string(data, offset=0):
    """Read a signed-length LUCA string used by the multilingual port."""
    if offset + 2 > len(data):
        raise ValueError("truncated LUCA string length")
    length = struct.unpack_from("<h", data, offset)[0]
    data_offset = offset + 2
    if length >= 0:
        encoding = "utf-16le"
        data_size = length * 2
        terminator_size = 2
    else:
        encoding = "utf-8"
        data_size = -length
        terminator_size = 1
    terminator_offset = data_offset + data_size
    end_offset = terminator_offset + terminator_size
    if end_offset > len(data):
        raise ValueError("truncated LUCA string data")
    if data[terminator_offset:end_offset] != b"\0" * terminator_size:
        raise ValueError("LUCA string terminator is missing")
    text = data[data_offset:terminator_offset].decode(encoding)
    return LucaString(
        text=text,
        encoding=encoding,
        offset=offset,
        data_offset=data_offset,
        data_size=data_size,
        end_offset=end_offset,
    )


def encode_luca_string(text, encoding):
    if encoding == "utf-16le":
        raw = text.encode(encoding)
        length = len(raw) // 2
        terminator = b"\0\0"
    elif encoding == "utf-8":
        raw = text.encode(encoding)
        length = -len(raw)
        terminator = b"\0"
    else:
        raise ValueError(f"unsupported LUCA string encoding: {encoding}")
    if not -0x8000 <= length <= 0x7FFF:
        raise ValueError("LUCA string is too long")
    return struct.pack("<h", length) + raw + terminator


def multilingual_strings(record, count=3, prefix_size=2):
    """Read the language slots from a LUCA dialogue record."""
    offset = prefix_size
    strings = []
    for _ in range(count):
        value = read_luca_string(record.params, offset)
        strings.append(value)
        offset = value.end_offset
    return tuple(strings), record.params[offset:]


def make_source_id(entry_id, record_ordinal, group_ordinal=0):
    """Return a stable, spoiler-neutral ID independent of byte offsets."""
    if entry_id < 0 or record_ordinal < 0 or group_ordinal < 0:
        raise ValueError("source ID components must be nonnegative")
    return (
        f"SRC_LUCA_E{entry_id:06d}_R{record_ordinal:06d}_G{group_ordinal:02d}"
    )


def classify_source_record(record):
    """Classify verified multilingual and service layouts without guessing."""
    if record.opcode not in TEXT_RECORD_LAYOUTS:
        return ClassifiedSourceRecord("structural")

    if (
        record.opcode == 36
        and record.flag == 3
        and len(record.fixed_params) == 2
        and record.length == 21
        and len(record.params) == 13
        and record.params[:8] == b"\0" * 8
        and record.params[8] in (0x03, 0x09, 0x0B)
    ):
        return ClassifiedSourceRecord(
            "service_nontext", layout="opcode36-service-v1"
        )

    layout = TEXT_RECORD_LAYOUTS[record.opcode]
    if record.flag != layout["flag"]:
        return ClassifiedSourceRecord(
            "unknown_candidate",
            error=f"unexpected flag {record.flag} for opcode {record.opcode}",
        )
    if len(record.fixed_params) != layout["fixed_count"]:
        return ClassifiedSourceRecord(
            "unknown_candidate",
            error=(
                f"unexpected fixed parameter count {len(record.fixed_params)} "
                f"for opcode {record.opcode}"
            ),
        )
    prefix_size = layout["prefix_size"]
    if len(record.params) < prefix_size:
        return ClassifiedSourceRecord(
            "unknown_candidate", error="multilingual prefix is truncated"
        )
    try:
        strings, tail = multilingual_strings(record, prefix_size=prefix_size)
    except (UnicodeDecodeError, ValueError) as exc:
        return ClassifiedSourceRecord(
            "unknown_candidate", error=f"multilingual decode failed: {type(exc).__name__}"
        )
    encodings = tuple(value.encoding for value in strings)
    if encodings != layout["encodings"]:
        return ClassifiedSourceRecord(
            "unknown_candidate",
            error=f"unexpected slot encodings for opcode {record.opcode}",
        )
    if any(not value.text for value in strings):
        return ClassifiedSourceRecord(
            "unknown_candidate", error="one or more source-language slots are empty"
        )
    if len(tail) not in layout["tail_sizes"]:
        return ClassifiedSourceRecord(
            "unknown_candidate",
            error=f"unexpected tail size {len(tail)} for opcode {record.opcode}",
        )
    if record.opcode == 36:
        if tail[0] not in (0x03, 0x05, 0x0A, 0x0B):
            return ClassifiedSourceRecord(
                "unknown_candidate", error="unexpected opcode 36 tail marker"
            )
    elif tail not in (b"\0\0\x02\0", b"\0\0\x03\0", b"\0\0\x04\0", b"\0\0\x05\0"):
        return ClassifiedSourceRecord(
            "unknown_candidate", error="unexpected opcode 40 tail value"
        )
    return ClassifiedSourceRecord(
        "translatable",
        layout=f"opcode{record.opcode}-multilingual-v1",
        prefix=record.params[:prefix_size],
        strings=strings,
        tail=tail,
    )


def replace_script_record(data, record, new_params):
    """Replace one record without relocating later bytecode."""
    fixed = struct.pack(
        f"<{len(record.fixed_params)}H", *record.fixed_params
    ) if record.fixed_params else b""
    raw = fixed + new_params
    new_length = 4 + len(raw)
    if new_length != record.length:
        raise ValueError(
            "record size changed; jump relocation is required before this edit is safe"
        )
    replacement = struct.pack("<HBB", new_length, record.opcode, record.flag) + raw
    out = bytearray(data)
    out[record.offset:record.offset + record.length] = replacement
    return bytes(out)


def decode_luca_lzw(data):
    """Decode the fixed-u16 LZW stream used by SCRIPT.PAK metadata."""
    if len(data) < 20:
        raise ValueError("LUCA LZW header is truncated")
    magic, raw_size, mode, code_count, repeated_size = struct.unpack_from(
        "<4s4I", data
    )
    if magic != LZW_MAGIC:
        raise ValueError("LUCA LZW magic is missing")
    if raw_size != repeated_size or mode != 1:
        raise ValueError("unsupported LUCA LZW header")
    if len(data) != 20 + code_count * 2:
        raise ValueError("LUCA LZW code stream has the wrong size")
    if not code_count:
        if raw_size:
            raise ValueError("empty LUCA LZW stream has a nonzero size")
        return b""

    codes = struct.unpack_from(f"<{code_count}H", data, 20)
    dictionary = {value: bytes((value,)) for value in range(256)}
    next_code = 257
    first = codes[0]
    if first not in dictionary:
        raise ValueError(f"invalid first LUCA LZW code: {first}")
    previous = dictionary[first]
    output = bytearray(previous)
    for code in codes[1:]:
        if code in dictionary:
            current = dictionary[code]
        elif code == next_code:
            current = previous + previous[:1]
        else:
            raise ValueError(f"invalid LUCA LZW code: {code}")
        output.extend(current)
        if next_code <= 0xFFFF:
            dictionary[next_code] = previous + current[:1]
            next_code += 1
        previous = current
    if len(output) != raw_size:
        raise ValueError(
            f"LUCA LZW size mismatch: expected {raw_size}, got {len(output)}"
        )
    return bytes(output)


def encode_luca_lzw(data):
    """Encode bytes with the deterministic LUCA fixed-u16 LZW variant."""
    if not data:
        return struct.pack("<4s4I", LZW_MAGIC, 0, 1, 0, 0)
    dictionary = {bytes((value,)): value for value in range(256)}
    next_code = 257
    codes = []
    current = bytes((data[0],))
    for value in data[1:]:
        candidate = current + bytes((value,))
        if candidate in dictionary:
            current = candidate
            continue
        codes.append(dictionary[current])
        if next_code <= 0xFFFF:
            dictionary[candidate] = next_code
            next_code += 1
        current = bytes((value,))
    codes.append(dictionary[current])
    return (
        struct.pack("<4s4I", LZW_MAGIC, len(data), 1, len(codes), len(data))
        + struct.pack(f"<{len(codes)}H", *codes)
    )


def _script_entries(pak):
    metadata_index = next(
        (entry.index for entry in pak.entries if entry.name == "_build_time"),
        pak.entry_count,
    )
    return pak.entries[:metadata_index]


def _record_target(record):
    """Return (destination name, field offset, target), or None."""
    params = record.params
    if record.opcode == 15:
        if len(params) != 4:
            raise ValueError(f"unexpected opcode 15 layout at {record.offset:#x}")
        return None, 0, struct.unpack_from("<I", params)[0]
    if record.opcode == 17:
        if len(params) != 6:
            raise ValueError(f"unexpected opcode 17 layout at {record.offset:#x}")
        return None, 2, struct.unpack_from("<I", params, 2)[0]
    if record.opcode in (18, 19):
        value = read_luca_string(params)
        if value.end_offset + 4 != len(params):
            raise ValueError(
                f"unexpected opcode {record.opcode} layout at {record.offset:#x}"
            )
        return None, value.end_offset, struct.unpack_from("<I", params, value.end_offset)[0]
    if record.opcode == 21:
        destination = read_luca_string(params)
        remaining = len(params) - destination.end_offset
        if remaining == 0:
            return None
        if remaining != 4:
            raise ValueError(f"unexpected opcode 21 layout at {record.offset:#x}")
        return (
            destination.text,
            destination.end_offset,
            struct.unpack_from("<I", params, destination.end_offset)[0],
        )
    if record.opcode == 22:
        destination = read_luca_string(params, 2)
        if destination.end_offset + 4 != len(params):
            raise ValueError(f"unexpected opcode 22 layout at {record.offset:#x}")
        return (
            destination.text,
            destination.end_offset,
            struct.unpack_from("<I", params, destination.end_offset)[0],
        )
    return None


def _pack_record(record, params):
    fixed = (
        struct.pack(f"<{len(record.fixed_params)}H", *record.fixed_params)
        if record.fixed_params
        else b""
    )
    length = 4 + len(fixed) + len(params)
    if length > 0xFFFF:
        raise ValueError(f"script record at {record.offset:#x} is too large")
    packed = struct.pack("<HBB", length, record.opcode, record.flag) + fixed + params
    return packed + (b"\0" if length & 1 else b"")


_LABEL_OFFSET = re.compile(rb":([0-9]+)(\([^)]*\),)")


def _relocate_script_labels(data, script_entries, offset_maps):
    raw = decode_luca_lzw(data)
    lines = raw.splitlines(keepends=True)
    if len(lines) != len(script_entries) + 1 or lines[0].strip(b"\r\n"):
        raise ValueError("unexpected _scr_label line layout")
    relocated = [lines[0]]
    label_count = 0
    for entry, line in zip(script_entries, lines[1:]):
        offset_map = offset_maps[entry.index]

        def replace(match):
            nonlocal label_count
            old_offset = int(match.group(1))
            if old_offset not in offset_map:
                raise ValueError(
                    f"_scr_label target is not a record start: "
                    f"entry={entry.index} offset={old_offset}"
                )
            label_count += 1
            return b":" + str(offset_map[old_offset]).encode("ascii") + match.group(2)

        relocated.append(_LABEL_OFFSET.sub(replace, line))
    return encode_luca_lzw(b"".join(relocated)), label_count


def relocate_script_records(pak, record_params):
    """Rebuild scripts after parameter edits and relocate every known target.

    ``record_params`` maps ``(entry_index, old_record_offset)`` to complete new
    ``ScriptRecord.params`` bytes. Offset-bearing opcodes are intentionally not
    editable through this API; their targets are rewritten automatically.
    """
    script_entries = _script_entries(pak)
    script_indexes = {entry.index for entry in script_entries}
    edits = dict(record_params)
    for entry_index, _ in edits:
        if entry_index not in script_indexes:
            raise ValueError(f"record edit targets a non-script entry: {entry_index}")

    original_data = {}
    original_records = {}
    records_by_offset = {}
    for entry in script_entries:
        data = pak.read_entry(entry)
        records = tuple(iter_script_records(data))
        if sum((record.length + 1) & ~1 for record in records) != len(data):
            raise ValueError(f"script entry {entry.index} did not parse to its boundary")
        original_data[entry.index] = data
        original_records[entry.index] = records
        records_by_offset[entry.index] = {record.offset: record for record in records}

    for key in edits:
        entry_index, record_offset = key
        record = records_by_offset[entry_index].get(record_offset)
        if record is None:
            raise ValueError(
                f"record edit does not point to a record start: {entry_index}:{record_offset}"
            )
        if record.opcode in TARGET_OPCODES:
            raise ValueError("offset-bearing records cannot be edited directly")

    offset_maps = {}
    provisional_params = {}
    for entry in script_entries:
        offset_map = {}
        new_offset = 0
        for record in original_records[entry.index]:
            offset_map[record.offset] = new_offset
            params = edits.get((entry.index, record.offset), record.params)
            provisional_params[(entry.index, record.offset)] = params
            new_offset += len(_pack_record(record, params))
        offset_maps[entry.index] = offset_map

    entries_by_name = {}
    for entry in script_entries:
        if entry.name in entries_by_name:
            raise ValueError(f"duplicate script entry name: {entry.name!r}")
        entries_by_name[entry.name] = entry

    replacements = {}
    reference_count = 0
    for entry in script_entries:
        rebuilt = bytearray()
        for record in original_records[entry.index]:
            params = provisional_params[(entry.index, record.offset)]
            target = _record_target(record)
            if target is not None:
                destination_name, field_offset, old_target = target
                destination = entry if destination_name is None else entries_by_name.get(destination_name)
                if destination is None:
                    raise ValueError(f"unknown target script: {destination_name!r}")
                destination_map = offset_maps[destination.index]
                if old_target not in destination_map:
                    raise ValueError(
                        f"target is not a record start: entry={destination.index} "
                        f"offset={old_target}"
                    )
                params = bytearray(params)
                struct.pack_into("<I", params, field_offset, destination_map[old_target])
                params = bytes(params)
                reference_count += 1
            rebuilt.extend(_pack_record(record, params))
        rebuilt = bytes(rebuilt)
        if rebuilt != original_data[entry.index]:
            replacements[entry.index] = rebuilt

    label_entry = next((entry for entry in pak.entries if entry.name == "_scr_label"), None)
    if label_entry is None:
        raise ValueError("SCRIPT.PAK has no _scr_label entry")
    labels, label_count = _relocate_script_labels(
        pak.read_entry(label_entry), script_entries, offset_maps
    )
    if labels != pak.read_entry(label_entry):
        replacements[label_entry.index] = labels

    return ScriptRelocation(
        replacements=replacements,
        offset_maps=offset_maps,
        record_count=sum(len(records) for records in original_records.values()),
        reference_count=reference_count,
        label_count=label_count,
    )


def validate_script_references(pak):
    """Validate all known script and _scr_label offsets in a built archive."""
    script_entries = _script_entries(pak)
    entries_by_name = {entry.name: entry for entry in script_entries}
    starts = {}
    records_by_entry = {}
    record_count = 0
    for entry in script_entries:
        data = pak.read_entry(entry)
        records = tuple(iter_script_records(data))
        if sum((record.length + 1) & ~1 for record in records) != len(data):
            raise ValueError(f"script entry {entry.index} did not parse to its boundary")
        records_by_entry[entry.index] = records
        starts[entry.index] = {record.offset for record in records}
        record_count += len(records)

    reference_count = 0
    for entry in script_entries:
        for record in records_by_entry[entry.index]:
            target = _record_target(record)
            if target is None:
                continue
            destination_name, _, target_offset = target
            destination = entry if destination_name is None else entries_by_name.get(destination_name)
            if destination is None or target_offset not in starts[destination.index]:
                raise ValueError(
                    f"unresolved script target: entry={entry.index} "
                    f"record={record.offset} target={destination_name!r}:{target_offset}"
                )
            reference_count += 1

    label_entry = next((entry for entry in pak.entries if entry.name == "_scr_label"), None)
    if label_entry is None:
        raise ValueError("SCRIPT.PAK has no _scr_label entry")
    raw_labels = decode_luca_lzw(pak.read_entry(label_entry))
    lines = raw_labels.splitlines(keepends=True)
    if len(lines) != len(script_entries) + 1 or lines[0].strip(b"\r\n"):
        raise ValueError("unexpected _scr_label line layout")
    label_count = 0
    for entry, line in zip(script_entries, lines[1:]):
        for match in _LABEL_OFFSET.finditer(line):
            target_offset = int(match.group(1))
            if target_offset not in starts[entry.index]:
                raise ValueError(
                    f"unresolved _scr_label target: entry={entry.index} "
                    f"offset={target_offset}"
                )
            label_count += 1
    return {
        "script_entries": len(script_entries),
        "records": record_count,
        "references": reference_count,
        "labels": label_count,
    }
