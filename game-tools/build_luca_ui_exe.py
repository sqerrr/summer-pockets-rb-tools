"""Build and optionally install the Russian LUCA runtime UI executable."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
from typing import Iterable

import capstone
from capstone.x86_const import X86_OP_IMM, X86_OP_MEM, X86_REG_INVALID, X86_REG_RIP
import pefile


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SOURCE = ROOT / "translation/ui/runtime-strings.json"
INSTALLED_EXE = ROOT / "Summer Pockets REFLECTION BLUE_Steam/SummerPocketsRB.exe"
PRISTINE_BACKUP = ROOT / "build/steam/SummerPocketsRB.pristine.exe"
ARTIFACT_EXE = ROOT / "build/steam/SummerPocketsRB.russian-ui.exe"
RECEIPT_PATH = ROOT / "build/steam/ui-exe-receipt.json"
WORK_DIR = ROOT / "build/steam/ui-exe-work"
STEAMLESS_DIR = ROOT / "build/tools/Steamless.v3.1.0.5"
STEAMLESS_CLI = STEAMLESS_DIR / "Steamless.CLI.exe"
STEAMLESS_X64_PLUGIN = STEAMLESS_DIR / "Plugins/Steamless.Unpacker.Variant31.x64.dll"

PACKED_SHA256 = "cddebe8e27acdb0f57679ba46b2224c599f9bc149a2ac8e54e3da36a9d8a94ca"
UNPACKED_SHA256 = "c30e660484903c75589421d4ab78dc19f4cb87b76ee0ae89adfb5d53c3cdc3b0"
STEAMLESS_CLI_SHA256 = "70cd54354865ede605ec0fbfadf15f5302aa85a777394f28b0de6acfd243e795"
STEAMLESS_X64_PLUGIN_SHA256 = "790f1974f97258058cb57c20787e8a2fcb5c16cca0911719b698580d74e38918"
GAME_PROCESS = "SummerPocketsRB.exe"
SECTION_NAME = b".ruui"
SECTION_CHARACTERISTICS = 0x40000040
DIR64 = 10

DOLLAR_TOKEN = r"\$[A-Za-z](?:\(\d+\)|\d+)?"
PRINTF_TOKEN = r"%(?:\d+\$)?[-+ #0']*(?:\*|\d+)?(?:\.(?:\*|\d+))?(?:hh|h|ll|l|j|z|t|L)?[diuoxXfFeEgGaAcspn%]"
PROTECTED_TOKEN_RE = re.compile(f"(?:{DOLLAR_TOKEN}|{PRINTF_TOKEN})")

# On the pinned clean hash these strings have no exact RIP-relative LEA ref in
# exception-directory code and no absolute qword occurrence. Nearby LEAs were
# also checked for the core strings so an adjacent label is not mistaken for a
# reference. Their original bytes remain because there is no safe target to
# redirect yet.
KNOWN_ZERO_REFERENCE_STRINGS = {}
INTERFACE_EXCLUDED_CATEGORIES = {"music_title", "date_label"}
ZERO_REFERENCE_EVIDENCE = (
    "unique NUL-terminated source string; zero supported refs across exception-directory "
    "runtime functions; zero absolute qword occurrences on sha256:" + UNPACKED_SHA256
)


@dataclass(frozen=True)
class SectionExtent:
    rva: int
    virtual_size: int
    raw_size: int


@dataclass(frozen=True)
class SectionView:
    name: str
    rva: int
    raw_offset: int
    raw_size: int
    executable: bool


@dataclass(frozen=True)
class SectionPlacement:
    header_offset: int
    raw_offset: int
    raw_size: int
    rva: int
    virtual_size: int
    size_of_image: int


@dataclass(frozen=True)
class StringTarget:
    source_file_offset: int
    source_text: str
    replacement: str
    scope: str
    category: str
    old_rva: int
    old_va: int


@dataclass(frozen=True)
class StringLocation:
    payload_offset: int
    raw_offset: int
    rva: int
    va: int
    encoded: bytes


@dataclass(frozen=True)
class DirectReference:
    source_file_offset: int
    instruction_rva: int
    instruction_file_offset: int
    instruction_size: int
    instruction_bytes: bytes
    displacement_offset: int
    displacement_size: int


@dataclass(frozen=True)
class PointerReference:
    source_file_offset: int
    cell_rva: int
    cell_file_offset: int


@dataclass(frozen=True)
class UnsupportedReference:
    source_file_offset: int
    kind: str
    rva: int
    file_offset: int
    detail: str


@dataclass(frozen=True)
class ReferenceException:
    target: StringTarget
    evidence: str
    action: str


@dataclass(frozen=True)
class BuildPlan:
    image_base: int
    targets: tuple[StringTarget, ...]
    locations: dict[int, StringLocation]
    direct_references: tuple[DirectReference, ...]
    pointer_references: tuple[PointerReference, ...]
    reference_exceptions: tuple[ReferenceException, ...]
    placement: SectionPlacement
    payload: bytes


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def align_up(value: int, alignment: int) -> int:
    if value < 0 or alignment <= 0:
        raise ValueError("alignment inputs must be non-negative and positive")
    return (value + alignment - 1) // alignment * alignment


def hx(value: int) -> str:
    return f"0x{value:X}"


def protected_tokens(text: str) -> tuple[str, ...]:
    matches = tuple(PROTECTED_TOKEN_RE.finditer(text))
    covered = {index for match in matches for index in range(match.start(), match.end())}
    for index, character in enumerate(text):
        if character == "$" and index not in covered:
            raise ValueError(f"unrecognized protected token at character {index}: {text!r}")
    return tuple(match.group(0) for match in matches)


def load_canonical(path: Path = CANONICAL_SOURCE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_canonical(config: dict, source_bytes: bytes | None = None) -> dict:
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("unsupported runtime UI string schema")
    if config.get("asset_id") != "runtime_ui_strings":
        raise ValueError("unexpected runtime UI asset ID")
    if config.get("status") != "draft":
        raise ValueError("runtime UI strings must remain draft until explicit user approval")

    target = config.get("target")
    expected_target = {
        "profile": "steam_luca",
        "file": "SummerPocketsRB.exe",
        "packed_sha256": "sha256:" + PACKED_SHA256,
        "steamless_unpacked_sha256": "sha256:" + UNPACKED_SHA256,
        "language_slot": "english",
    }
    if not isinstance(target, dict) or any(target.get(key) != value for key, value in expected_target.items()):
        raise ValueError("canonical runtime UI target or pinned hashes changed")

    entries = config.get("entries")
    if not isinstance(entries, list) or config.get("entry_count") != len(entries):
        raise ValueError("runtime UI entry count does not match entries")

    seen_offsets: set[int] = set()
    scope_counts: dict[str, int] = {"core": 0, "options": 0, "later": 0}
    for index, row in enumerate(entries):
        if not isinstance(row, dict):
            raise ValueError(f"runtime UI entry {index} is not an object")
        offset = row.get("file_offset")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError(f"runtime UI entry {index} has an invalid file offset")
        if offset in seen_offsets:
            raise ValueError(f"duplicate canonical file offset: {hx(offset)}")
        seen_offsets.add(offset)
        try:
            offset_hex = int(row.get("file_offset_hex", ""), 0)
        except (TypeError, ValueError) as error:
            raise ValueError(f"runtime UI entry {index} has an invalid hexadecimal offset") from error
        if offset_hex != offset:
            raise ValueError(f"canonical decimal/hex offset mismatch at {hx(offset)}")

        source_text = row.get("text_en")
        replacement = row.get("text_ru")
        if not isinstance(source_text, str) or not isinstance(replacement, str):
            raise ValueError(f"runtime UI entry at {hx(offset)} has non-string text")
        if "\0" in source_text or "\0" in replacement:
            raise ValueError(f"runtime UI entry at {hx(offset)} contains an embedded NUL")
        source_encoded = source_text.encode("utf-8") + b"\0"
        if protected_tokens(source_text) != protected_tokens(replacement):
            raise ValueError(f"protected token sequence changed at {hx(offset)}")
        if row.get("status") != "draft":
            raise ValueError(f"runtime UI entry at {hx(offset)} is not draft")
        scope = row.get("build_scope")
        if scope not in scope_counts:
            raise ValueError(f"unsupported build scope at {hx(offset)}: {scope!r}")
        scope_counts[scope] += 1

        if source_bytes is not None:
            if offset > 0 and source_bytes[offset - 1] != 0:
                parent_start = source_bytes.rfind(b"\0", 0, offset) + 1
                parent_end = source_bytes.find(b"\0", offset)
                raise ValueError(
                    f"canonical string starts inside a NUL field at {hx(offset)}; "
                    f"containing field is {hx(parent_start)}-{hx(parent_end)}"
                )
            end = offset + len(source_encoded)
            if end > len(source_bytes) or source_bytes[offset:end] != source_encoded:
                actual = source_bytes[offset:end]
                raise ValueError(
                    f"source English bytes differ at {hx(offset)}: "
                    f"expected {source_encoded!r}, got {actual!r}"
                )
    return {"entry_count": len(entries), "scope_counts": scope_counts}


def select_scope_rows(config: dict, scope: str) -> tuple[dict, ...]:
    if scope not in {"options", "core", "first_wave", "interface", "all"}:
        raise ValueError(f"unsupported runtime UI scope: {scope}")
    if scope == "all":
        rows = config["entries"]
    elif scope == "interface":
        rows = (row for row in config["entries"] if row.get("category") not in INTERFACE_EXCLUDED_CATEGORIES)
    elif scope == "first_wave":
        rows = (row for row in config["entries"] if row["build_scope"] in {"core", "options"})
    else:
        rows = (row for row in config["entries"] if row["build_scope"] == scope)
    return tuple(sorted(rows, key=lambda row: row["file_offset"]))


def semantic_rows(rows: Iterable[dict]) -> tuple[dict, ...]:
    return tuple(row for row in rows if row["text_en"] != row["text_ru"])


def partition_zero_reference_targets(
    targets: Iterable[StringTarget],
    reference_counts: dict[int, int],
) -> tuple[tuple[StringTarget, ...], tuple[ReferenceException, ...]]:
    active: list[StringTarget] = []
    exceptions: list[ReferenceException] = []
    unexpected: list[int] = []
    for target in targets:
        if reference_counts[target.source_file_offset]:
            active.append(target)
            continue
        expected_source = KNOWN_ZERO_REFERENCE_STRINGS.get(target.source_file_offset)
        if target.source_text != expected_source:
            unexpected.append(target.source_file_offset)
            continue
        exceptions.append(ReferenceException(
            target=target,
            evidence=ZERO_REFERENCE_EVIDENCE,
            action="original English string retained; no .ruui string emitted",
        ))
    if unexpected:
        raise ValueError(
            "semantic runtime UI translations have zero supported references: "
            + ", ".join(hx(offset) for offset in unexpected)
        )
    if not active:
        raise ValueError("scope has no safely referenced semantic runtime UI translations")
    return tuple(active), tuple(exceptions)


def derive_section_placement(
    *,
    source_size: int,
    file_alignment: int,
    section_alignment: int,
    size_of_headers: int,
    section_table_offset: int,
    number_of_sections: int,
    sections: Iterable[SectionExtent],
    payload_size: int,
) -> SectionPlacement:
    if payload_size <= 0:
        raise ValueError("the .ruui payload must not be empty")
    extents = tuple(sections)
    if not extents:
        raise ValueError("PE has no sections")
    header_offset = section_table_offset + number_of_sections * 40
    if header_offset + 40 > size_of_headers:
        raise ValueError("PE has no spare section-header slot")
    raw_offset = align_up(source_size, file_alignment)
    image_end = max(section.rva + max(section.virtual_size, section.raw_size) for section in extents)
    rva = align_up(image_end, section_alignment)
    raw_size = align_up(payload_size, file_alignment)
    size_of_image = align_up(rva + payload_size, section_alignment)
    return SectionPlacement(header_offset, raw_offset, raw_size, rva, payload_size, size_of_image)


def build_string_payload(
    targets: Iterable[StringTarget],
    *,
    section_rva: int,
    section_raw_offset: int,
    image_base: int,
) -> tuple[bytes, dict[int, StringLocation]]:
    payload = bytearray()
    locations: dict[int, StringLocation] = {}
    for target in sorted(targets, key=lambda item: item.source_file_offset):
        aligned = align_up(len(payload), 8)
        payload.extend(b"\0" * (aligned - len(payload)))
        encoded = target.replacement.encode("utf-8") + b"\0"
        locations[target.source_file_offset] = StringLocation(
            payload_offset=aligned,
            raw_offset=section_raw_offset + aligned,
            rva=section_rva + aligned,
            va=image_base + section_rva + aligned,
            encoded=encoded,
        )
        payload.extend(encoded)
    return bytes(payload), locations


def _section_views(pe: pefile.PE) -> tuple[SectionView, ...]:
    return tuple(
        SectionView(
            name=section.Name.rstrip(b"\0").decode("ascii", errors="replace"),
            rva=section.VirtualAddress,
            raw_offset=section.PointerToRawData,
            raw_size=section.SizeOfRawData,
            executable=bool(section.Characteristics & 0x20000000),
        )
        for section in pe.sections
        if section.SizeOfRawData
    )


def collect_dir64_relocations(pe: pefile.PE) -> set[int]:
    result: set[int] = set()
    for block in getattr(pe, "DIRECTORY_ENTRY_BASERELOC", ()):
        for entry in block.entries:
            if entry.type == DIR64:
                result.add(entry.rva)
    return result


def classify_pointer_cells(
    data: bytes,
    sections: Iterable[SectionView],
    dir64_rvas: set[int],
    old_va_to_offset: dict[int, int],
) -> tuple[tuple[PointerReference, ...], tuple[UnsupportedReference, ...]]:
    pointers: list[PointerReference] = []
    unsupported: list[UnsupportedReference] = []
    for old_va, source_offset in old_va_to_offset.items():
        needle = struct.pack("<Q", old_va)
        for section in sections:
            start = section.raw_offset
            end = min(len(data), start + section.raw_size)
            cursor = start
            while True:
                cursor = data.find(needle, cursor, end)
                if cursor < 0:
                    break
                cell_rva = section.rva + cursor - start
                if section.executable:
                    unsupported.append(UnsupportedReference(
                        source_offset,
                        "absolute_qword_in_executable_section",
                        cell_rva,
                        cursor,
                        section.name,
                    ))
                elif cell_rva not in dir64_rvas:
                    unsupported.append(UnsupportedReference(
                        source_offset,
                        "absolute_qword_without_dir64_relocation",
                        cell_rva,
                        cursor,
                        section.name,
                    ))
                else:
                    pointers.append(PointerReference(source_offset, cell_rva, cursor))
                cursor += 1
    pointer_map = {(item.source_file_offset, item.cell_rva): item for item in pointers}
    unsupported_map = {
        (item.source_file_offset, item.kind, item.rva, item.file_offset): item
        for item in unsupported
    }
    return (
        tuple(sorted(pointer_map.values(), key=lambda item: (item.source_file_offset, item.cell_rva))),
        tuple(sorted(unsupported_map.values(), key=lambda item: (item.source_file_offset, item.rva, item.kind))),
    )


def _capstone() -> capstone.Cs:
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    return decoder


def discover_direct_references(
    data: bytes,
    pe: pefile.PE,
    old_va_to_offset: dict[int, int],
) -> tuple[tuple[DirectReference, ...], tuple[UnsupportedReference, ...]]:
    runtime_functions = getattr(pe, "DIRECTORY_ENTRY_EXCEPTION", None)
    if not runtime_functions:
        raise ValueError("clean PE has no exception-directory runtime functions")

    decoder = _capstone()
    image_base = pe.OPTIONAL_HEADER.ImageBase
    direct: list[DirectReference] = []
    unsupported: list[UnsupportedReference] = []
    seen_functions: set[tuple[int, int]] = set()
    for entry in runtime_functions:
        begin = int(entry.struct.BeginAddress)
        end = int(entry.struct.EndAddress)
        if begin >= end or (begin, end) in seen_functions:
            continue
        seen_functions.add((begin, end))
        section = pe.get_section_by_rva(begin)
        section_end = 0 if section is None else section.VirtualAddress + max(
            section.Misc_VirtualSize,
            section.SizeOfRawData,
        )
        if section is None or not (section.Characteristics & 0x20000000) or end > section_end:
            raise ValueError(f"runtime function is outside one executable section: {hx(begin)}-{hx(end)}")
        blob = pe.get_data(begin, end - begin)
        if len(blob) != end - begin:
            raise ValueError(f"runtime function read is truncated: {hx(begin)}-{hx(end)}")
        instructions = tuple(decoder.disasm(blob, image_base + begin))
        expected_address = image_base + begin
        for instruction in instructions:
            if instruction.address != expected_address:
                raise ValueError(f"runtime function did not decode contiguously at {hx(begin)}")
            expected_address += instruction.size
            for operand in instruction.operands:
                target_va: int | None = None
                is_rip_memory = False
                if operand.type == X86_OP_MEM:
                    if operand.mem.base == X86_REG_RIP:
                        target_va = instruction.address + instruction.size + operand.mem.disp
                        is_rip_memory = True
                    elif operand.mem.base == X86_REG_INVALID and operand.mem.index == X86_REG_INVALID:
                        target_va = operand.mem.disp
                elif operand.type == X86_OP_IMM:
                    target_va = operand.imm
                if target_va not in old_va_to_offset:
                    continue

                source_offset = old_va_to_offset[target_va]
                instruction_rva = instruction.address - image_base
                instruction_file_offset = pe.get_offset_from_rva(instruction_rva)
                if (
                    is_rip_memory
                    and instruction.mnemonic == "lea"
                    and instruction.disp_size == 4
                    and instruction.disp_offset > 0
                ):
                    direct.append(DirectReference(
                        source_file_offset=source_offset,
                        instruction_rva=instruction_rva,
                        instruction_file_offset=instruction_file_offset,
                        instruction_size=instruction.size,
                        instruction_bytes=bytes(instruction.bytes),
                        displacement_offset=instruction.disp_offset,
                        displacement_size=instruction.disp_size,
                    ))
                else:
                    unsupported.append(UnsupportedReference(
                        source_file_offset=source_offset,
                        kind="unsupported_code_reference",
                        rva=instruction_rva,
                        file_offset=instruction_file_offset,
                        detail=f"{instruction.mnemonic} {instruction.op_str}",
                    ))
        # This executable has exception ranges that continue into embedded byte
        # tables after a return. Capstone stops at the first non-instruction;
        # decoded instructions still have to be contiguous from BeginAddress.

    direct_map = {
        (item.source_file_offset, item.instruction_rva, item.displacement_offset): item
        for item in direct
    }
    unsupported_map = {
        (item.source_file_offset, item.kind, item.rva, item.file_offset): item
        for item in unsupported
    }
    return (
        tuple(sorted(direct_map.values(), key=lambda item: (item.source_file_offset, item.instruction_rva))),
        tuple(sorted(unsupported_map.values(), key=lambda item: (item.source_file_offset, item.rva))),
    )


def _parse_clean_pe(data: bytes) -> pefile.PE:
    pe = pefile.PE(data=data, fast_load=False)
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("clean executable is not an x64 PE32+ image")
    return pe


def _targets_from_rows(pe: pefile.PE, rows: Iterable[dict]) -> tuple[StringTarget, ...]:
    targets = []
    image_base = pe.OPTIONAL_HEADER.ImageBase
    old_vas: set[int] = set()
    for row in rows:
        offset = row["file_offset"]
        try:
            rva = pe.get_rva_from_offset(offset)
        except pefile.PEFormatError as error:
            raise ValueError(f"canonical string is outside PE sections: {hx(offset)}") from error
        section = pe.get_section_by_rva(rva)
        if section is None or pe.get_offset_from_rva(rva) != offset:
            raise ValueError(f"canonical string offset does not map exactly to an RVA: {hx(offset)}")
        old_va = image_base + rva
        if old_va in old_vas:
            raise ValueError(f"multiple canonical strings map to one VA: {hx(old_va)}")
        old_vas.add(old_va)
        targets.append(StringTarget(
            source_file_offset=offset,
            source_text=row["text_en"],
            replacement=row["text_ru"],
            scope=row["build_scope"],
            category=row.get("category", ""),
            old_rva=rva,
            old_va=old_va,
        ))
    return tuple(sorted(targets, key=lambda item: item.source_file_offset))


def prepare_build_plan(clean_data: bytes, rows: Iterable[dict]) -> BuildPlan:
    pe = _parse_clean_pe(clean_data)
    targets = _targets_from_rows(pe, rows)
    if not targets:
        raise ValueError("scope contains no semantic runtime UI translations")
    old_va_to_offset = {target.old_va: target.source_file_offset for target in targets}
    direct, unsupported_code = discover_direct_references(clean_data, pe, old_va_to_offset)
    dir64_rvas = collect_dir64_relocations(pe)
    pointers, unsupported_pointers = classify_pointer_cells(
        clean_data,
        _section_views(pe),
        dir64_rvas,
        old_va_to_offset,
    )
    unsupported = unsupported_code + unsupported_pointers
    if unsupported:
        first = unsupported[0]
        raise ValueError(
            f"unsupported reference for {hx(first.source_file_offset)} at RVA {hx(first.rva)}: "
            f"{first.kind} ({first.detail})"
        )

    ref_counts = {target.source_file_offset: 0 for target in targets}
    for reference in direct:
        ref_counts[reference.source_file_offset] += 1
    for reference in pointers:
        ref_counts[reference.source_file_offset] += 1
    targets, reference_exceptions = partition_zero_reference_targets(targets, ref_counts)

    section_table_offset = (
        pe.DOS_HEADER.e_lfanew
        + 4
        + pe.FILE_HEADER.sizeof()
        + pe.FILE_HEADER.SizeOfOptionalHeader
    )
    provisional_payload, _ = build_string_payload(
        targets,
        section_rva=0,
        section_raw_offset=0,
        image_base=pe.OPTIONAL_HEADER.ImageBase,
    )
    placement = derive_section_placement(
        source_size=len(clean_data),
        file_alignment=pe.OPTIONAL_HEADER.FileAlignment,
        section_alignment=pe.OPTIONAL_HEADER.SectionAlignment,
        size_of_headers=pe.OPTIONAL_HEADER.SizeOfHeaders,
        section_table_offset=section_table_offset,
        number_of_sections=pe.FILE_HEADER.NumberOfSections,
        sections=(
            SectionExtent(section.VirtualAddress, section.Misc_VirtualSize, section.SizeOfRawData)
            for section in pe.sections
        ),
        payload_size=len(provisional_payload),
    )
    if any(clean_data[placement.header_offset:placement.header_offset + 40]):
        raise ValueError("spare PE section-header slot is not zero-filled")
    payload, locations = build_string_payload(
        targets,
        section_rva=placement.rva,
        section_raw_offset=placement.raw_offset,
        image_base=pe.OPTIONAL_HEADER.ImageBase,
    )
    if len(payload) != placement.virtual_size:
        raise AssertionError("payload placement changed between passes")
    return BuildPlan(
        image_base=pe.OPTIONAL_HEADER.ImageBase,
        targets=targets,
        locations=locations,
        direct_references=direct,
        pointer_references=pointers,
        reference_exceptions=reference_exceptions,
        placement=placement,
        payload=payload,
    )


def build_image(clean_data: bytes, plan: BuildPlan) -> bytes:
    pe = _parse_clean_pe(clean_data)
    placement = plan.placement
    image = bytearray(clean_data)
    image.extend(b"\0" * (placement.raw_offset - len(image)))
    image.extend(plan.payload)
    image.extend(b"\0" * (placement.raw_size - len(plan.payload)))

    section_header = struct.pack(
        "<8sIIIIIIHHI",
        SECTION_NAME.ljust(8, b"\0"),
        placement.virtual_size,
        placement.rva,
        placement.raw_size,
        placement.raw_offset,
        0,
        0,
        0,
        0,
        SECTION_CHARACTERISTICS,
    )
    if any(image[placement.header_offset:placement.header_offset + 40]):
        raise ValueError("new section header preimage changed")
    image[placement.header_offset:placement.header_offset + 40] = section_header

    struct.pack_into(
        "<H",
        image,
        pe.FILE_HEADER.get_field_absolute_offset("NumberOfSections"),
        pe.FILE_HEADER.NumberOfSections + 1,
    )
    struct.pack_into(
        "<I",
        image,
        pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfImage"),
        placement.size_of_image,
    )
    struct.pack_into(
        "<I",
        image,
        pe.OPTIONAL_HEADER.get_field_absolute_offset("SizeOfInitializedData"),
        pe.OPTIONAL_HEADER.SizeOfInitializedData + placement.raw_size,
    )

    patched_displacements: set[int] = set()
    for reference in plan.direct_references:
        start = reference.instruction_file_offset
        end = start + reference.instruction_size
        if bytes(image[start:end]) != reference.instruction_bytes:
            raise ValueError(f"instruction preimage mismatch at {hx(start)}")
        displacement_file_offset = start + reference.displacement_offset
        if displacement_file_offset in patched_displacements:
            raise ValueError(f"duplicate instruction displacement patch at {hx(displacement_file_offset)}")
        patched_displacements.add(displacement_file_offset)
        new_va = plan.locations[reference.source_file_offset].va
        instruction_va = plan.image_base + reference.instruction_rva
        displacement = new_va - (instruction_va + reference.instruction_size)
        if not -(1 << 31) <= displacement < (1 << 31):
            raise ValueError("new .ruui section is outside signed disp32 range")
        struct.pack_into("<i", image, displacement_file_offset, displacement)

    patched_pointers: set[int] = set()
    target_by_offset = {target.source_file_offset: target for target in plan.targets}
    for reference in plan.pointer_references:
        if reference.cell_file_offset in patched_pointers:
            raise ValueError(f"duplicate absolute pointer patch at {hx(reference.cell_file_offset)}")
        patched_pointers.add(reference.cell_file_offset)
        old_va = target_by_offset[reference.source_file_offset].old_va
        if struct.unpack_from("<Q", image, reference.cell_file_offset)[0] != old_va:
            raise ValueError(f"absolute pointer preimage mismatch at {hx(reference.cell_file_offset)}")
        struct.pack_into(
            "<Q",
            image,
            reference.cell_file_offset,
            plan.locations[reference.source_file_offset].va,
        )

    checksum_offset = pe.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum")
    struct.pack_into("<I", image, checksum_offset, 0)
    checksum = pefile.PE(data=bytes(image), fast_load=False).generate_checksum()
    struct.pack_into("<I", image, checksum_offset, checksum)
    return bytes(image)


def validate_artifact(
    clean_data: bytes,
    artifact_path: Path,
    plan: BuildPlan,
    canonical_rows: Iterable[dict],
) -> dict:
    artifact_data = artifact_path.read_bytes()
    source_pe = _parse_clean_pe(clean_data)
    built_pe = _parse_clean_pe(artifact_data)
    placement = plan.placement
    if built_pe.FILE_HEADER.NumberOfSections != source_pe.FILE_HEADER.NumberOfSections + 1:
        raise ValueError("artifact section count validation failed")
    section = built_pe.sections[-1]
    if section.Name.rstrip(b"\0") != SECTION_NAME:
        raise ValueError("artifact .ruui section name validation failed")
    if section.Characteristics != SECTION_CHARACTERISTICS:
        raise ValueError("artifact .ruui section characteristics validation failed")
    if (
        section.VirtualAddress != placement.rva
        or section.Misc_VirtualSize != placement.virtual_size
        or section.PointerToRawData != placement.raw_offset
        or section.SizeOfRawData != placement.raw_size
    ):
        raise ValueError("artifact .ruui section placement validation failed")
    if built_pe.OPTIONAL_HEADER.SizeOfImage != placement.size_of_image:
        raise ValueError("artifact SizeOfImage validation failed")
    if built_pe.OPTIONAL_HEADER.SizeOfInitializedData != (
        source_pe.OPTIONAL_HEADER.SizeOfInitializedData + placement.raw_size
    ):
        raise ValueError("artifact SizeOfInitializedData validation failed")
    if built_pe.generate_checksum() != built_pe.OPTIONAL_HEADER.CheckSum:
        raise ValueError("artifact checksum validation failed")

    decoder = _capstone()
    for reference in plan.direct_references:
        location = plan.locations[reference.source_file_offset]
        start = reference.instruction_file_offset
        actual_bytes = artifact_data[start:start + reference.instruction_size]
        expected_bytes = bytearray(reference.instruction_bytes)
        displacement = location.va - (
            plan.image_base + reference.instruction_rva + reference.instruction_size
        )
        struct.pack_into("<i", expected_bytes, reference.displacement_offset, displacement)
        if actual_bytes != bytes(expected_bytes):
            raise ValueError(f"patched instruction bytes differ at {hx(start)}")
        decoded = tuple(decoder.disasm(
            actual_bytes,
            plan.image_base + reference.instruction_rva,
            count=1,
        ))
        if len(decoded) != 1:
            raise ValueError(f"patched instruction no longer decodes at {hx(start)}")
        instruction = decoded[0]
        targets = [
            instruction.address + instruction.size + operand.mem.disp
            for operand in instruction.operands
            if operand.type == X86_OP_MEM and operand.mem.base == X86_REG_RIP
        ]
        if (
            instruction.mnemonic != "lea"
            or instruction.disp_size != 4
            or targets != [location.va]
        ):
            raise ValueError(f"patched instruction target differs at {hx(start)}")

    dir64_rvas = collect_dir64_relocations(built_pe)
    for reference in plan.pointer_references:
        location = plan.locations[reference.source_file_offset]
        if struct.unpack_from("<Q", artifact_data, reference.cell_file_offset)[0] != location.va:
            raise ValueError(f"patched absolute pointer differs at {hx(reference.cell_file_offset)}")
        if reference.cell_rva not in dir64_rvas:
            raise ValueError(f"DIR64 relocation was lost at RVA {hx(reference.cell_rva)}")

    for target in plan.targets:
        location = plan.locations[target.source_file_offset]
        if artifact_data[location.raw_offset:location.raw_offset + len(location.encoded)] != location.encoded:
            raise ValueError(f"new UTF-8 string read-back differs for {hx(target.source_file_offset)}")

    original_count = 0
    for row in canonical_rows:
        original = row["text_en"].encode("utf-8") + b"\0"
        offset = row["file_offset"]
        if clean_data[offset:offset + len(original)] != original:
            raise ValueError(f"clean source string changed before validation at {hx(offset)}")
        if artifact_data[offset:offset + len(original)] != original:
            raise ValueError(f"original string was modified at {hx(offset)}")
        original_count += 1

    return {
        "pe_reparsed": True,
        "checksum_matches": True,
        "section_count_incremented": True,
        "section_read_only_initialized_data": True,
        "section_placement_matches": True,
        "size_of_image_matches": True,
        "size_of_initialized_data_matches": True,
        "all_direct_instructions_decode": True,
        "all_direct_targets_match": True,
        "all_pointer_targets_match": True,
        "all_pointer_cells_retain_dir64_relocation": True,
        "all_new_utf8_strings_read_back": True,
        "all_original_strings_unchanged": True,
        "original_string_count_checked": original_count,
        "direct_reference_count_checked": len(plan.direct_references),
        "pointer_reference_count_checked": len(plan.pointer_references),
        "new_string_count_checked": len(plan.targets),
    }


def assert_hash(path: Path, expected_hash: str, label: str) -> str:
    if not path.is_file():
        raise SystemExit(f"ERROR: {label} is missing: {path}")
    actual = digest_file(path)
    if actual != expected_hash:
        raise SystemExit(f"ERROR: wrong {label} hash: expected {expected_hash}, got {actual}")
    return actual


def verify_steamless() -> dict:
    return {
        "cli": str(STEAMLESS_CLI),
        "cli_sha256": "sha256:" + assert_hash(
            STEAMLESS_CLI,
            STEAMLESS_CLI_SHA256,
            "pinned Steamless CLI",
        ),
        "x64_plugin": str(STEAMLESS_X64_PLUGIN),
        "x64_plugin_sha256": "sha256:" + assert_hash(
            STEAMLESS_X64_PLUGIN,
            STEAMLESS_X64_PLUGIN_SHA256,
            "pinned Steamless x64 plugin",
        ),
    }


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


def atomic_verified_copy(source: Path, destination: Path, expected_hash: str) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        shutil.copy2(source, temporary)
        if digest_file(temporary) != expected_hash:
            raise ValueError(f"copied file hash mismatch for {destination}")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    actual = digest_file(destination)
    if actual != expected_hash:
        raise ValueError(f"destination hash mismatch after atomic copy: {destination}")
    return actual


def ensure_pristine_backup(
    installed: Path = INSTALLED_EXE,
    backup: Path = PRISTINE_BACKUP,
    expected_hash: str = PACKED_SHA256,
) -> Path:
    if backup.exists():
        assert_hash(backup, expected_hash, "packed pristine EXE backup")
        return backup
    assert_hash(installed, expected_hash, "installed packed EXE")
    atomic_verified_copy(installed, backup, expected_hash)
    assert_hash(backup, expected_hash, "packed pristine EXE backup")
    return backup


def select_packed_source(
    *,
    require_backup: bool,
    installed: Path = INSTALLED_EXE,
    backup: Path = PRISTINE_BACKUP,
    expected_hash: str = PACKED_SHA256,
) -> Path:
    if backup.exists():
        assert_hash(backup, expected_hash, "packed pristine EXE backup")
        return backup
    if require_backup:
        return ensure_pristine_backup(installed, backup, expected_hash)
    assert_hash(installed, expected_hash, "installed packed EXE")
    return installed


def unpack_packed_source(source: Path) -> tuple[Path, dict]:
    assert_hash(source, PACKED_SHA256, "packed EXE source")
    steamless = verify_steamless()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for stale in WORK_DIR.glob("*.unpacked.exe"):
        stale.unlink()
    working_packed = WORK_DIR / "SummerPocketsRB.packed.exe"
    atomic_verified_copy(source, working_packed, PACKED_SHA256)
    result = subprocess.run(
        [str(STEAMLESS_CLI), "--quiet", "--recalcchecksum", str(working_packed)],
        cwd=STEAMLESS_DIR,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(
            "ERROR: pinned Steamless failed with exit code "
            f"{result.returncode}: {(result.stdout + result.stderr).strip()}"
        )
    candidates = tuple(sorted(WORK_DIR.glob("*.unpacked.exe")))
    if len(candidates) != 1:
        raise SystemExit(f"ERROR: expected one Steamless .unpacked.exe, found {len(candidates)}")
    unpacked = candidates[0]
    unpacked_hash = assert_hash(unpacked, UNPACKED_SHA256, "Steamless clean unpacked EXE")
    return unpacked, {
        **steamless,
        "arguments": ["--quiet", "--recalcchecksum", str(working_packed)],
        "working_packed": str(working_packed),
        "working_packed_sha256": "sha256:" + PACKED_SHA256,
        "unpacked": str(unpacked),
        "unpacked_sha256": "sha256:" + unpacked_hash,
    }


def install_artifact(
    artifact: Path = ARTIFACT_EXE,
    installed: Path = INSTALLED_EXE,
    backup: Path = PRISTINE_BACKUP,
    artifact_hash: str | None = None,
) -> str:
    if game_is_running():
        raise SystemExit("ERROR: the game is running; Russian UI EXE was not installed")
    assert_hash(backup, PACKED_SHA256, "packed pristine EXE backup")
    expected = artifact_hash or digest_file(artifact)
    assert_hash(artifact, expected, "validated Russian UI EXE artifact")
    return atomic_verified_copy(artifact, installed, expected)


def restore_installed(
    installed: Path = INSTALLED_EXE,
    backup: Path = PRISTINE_BACKUP,
) -> str:
    if game_is_running():
        raise SystemExit("ERROR: the game is running; packed pristine EXE was not restored")
    assert_hash(backup, PACKED_SHA256, "packed pristine EXE backup")
    restored = atomic_verified_copy(backup, installed, PACKED_SHA256)
    return restored


def _reference_receipt(plan: BuildPlan, artifact_data: bytes) -> tuple[list[dict], list[dict]]:
    direct = []
    for reference in plan.direct_references:
        start = reference.instruction_file_offset
        direct.append({
            "source_file_offset": hx(reference.source_file_offset),
            "instruction_rva": hx(reference.instruction_rva),
            "instruction_file_offset": hx(start),
            "displacement_file_offset": hx(start + reference.displacement_offset),
            "old_instruction": reference.instruction_bytes.hex(" "),
            "new_instruction": artifact_data[start:start + reference.instruction_size].hex(" "),
            "new_target_va": hx(plan.locations[reference.source_file_offset].va),
        })
    pointers = [{
        "source_file_offset": hx(reference.source_file_offset),
        "cell_rva": hx(reference.cell_rva),
        "cell_file_offset": hx(reference.cell_file_offset),
        "relocation_type": "IMAGE_REL_BASED_DIR64",
        "new_target_va": hx(plan.locations[reference.source_file_offset].va),
    } for reference in plan.pointer_references]
    return direct, pointers


def build_receipt(
    *,
    scope: str,
    config: dict,
    canonical_validation: dict,
    selected_rows: tuple[dict, ...],
    plan: BuildPlan,
    packed_source: Path,
    unpack_details: dict,
    artifact_path: Path,
    validation: dict,
) -> dict:
    artifact_data = artifact_path.read_bytes()
    direct_refs, pointer_refs = _reference_receipt(plan, artifact_data)
    direct_by_offset: dict[int, list[dict]] = {}
    pointer_by_offset: dict[int, list[dict]] = {}
    for reference in direct_refs:
        direct_by_offset.setdefault(int(reference["source_file_offset"], 0), []).append(reference)
    for reference in pointer_refs:
        pointer_by_offset.setdefault(int(reference["source_file_offset"], 0), []).append(reference)
    target_by_offset = {target.source_file_offset: target for target in plan.targets}
    strings = []
    for offset in sorted(target_by_offset):
        target = target_by_offset[offset]
        location = plan.locations[offset]
        strings.append({
            "source_file_offset": hx(offset),
            "source_rva": hx(target.old_rva),
            "source_va": hx(target.old_va),
            "source_text": target.source_text,
            "replacement": target.replacement,
            "replacement_utf8_length": len(location.encoded) - 1,
            "scope": target.scope,
            "category": target.category,
            "new_file_offset": hx(location.raw_offset),
            "new_rva": hx(location.rva),
            "new_va": hx(location.va),
            "direct_reference_count": len(direct_by_offset.get(offset, ())),
            "pointer_reference_count": len(pointer_by_offset.get(offset, ())),
            "direct_references": direct_by_offset.get(offset, []),
            "pointer_references": pointer_by_offset.get(offset, []),
        })
    no_op_count = sum(row["text_en"] == row["text_ru"] for row in selected_rows)
    exceptions = [{
        "source_file_offset": hx(item.target.source_file_offset),
        "source_text": item.target.source_text,
        "replacement_not_emitted": item.target.replacement,
        "evidence": item.evidence,
        "action": item.action,
    } for item in plan.reference_exceptions]
    return {
        "schema_version": 1,
        "build_mode": "luca_runtime_ui_exe_relocation",
        "scope": scope,
        "canonical_source": str(CANONICAL_SOURCE),
        "canonical_source_sha256": "sha256:" + digest_file(CANONICAL_SOURCE),
        "canonical_status": config["status"],
        "canonical_validation": canonical_validation,
        "packed_source": str(packed_source),
        "packed_source_sha256": "sha256:" + PACKED_SHA256,
        "steamless": unpack_details,
        "artifact": str(artifact_path),
        "artifact_sha256": "sha256:" + digest_bytes(artifact_data),
        "artifact_size": len(artifact_data),
        "counts": {
            "canonical_entries": len(config["entries"]),
            "selected_entries": len(selected_rows),
            "exact_no_op_entries_skipped": no_op_count,
            "semantic_strings_selected": len(plan.targets) + len(plan.reference_exceptions),
            "semantic_strings_relocated": len(plan.targets),
            "direct_instruction_references": len(plan.direct_references),
            "dir64_pointer_references": len(plan.pointer_references),
            "unsupported_references": 0,
            "known_zero_reference_exceptions": len(plan.reference_exceptions),
            "unexpected_zero_reference_semantic_strings": 0,
        },
        "new_section": {
            "name": SECTION_NAME.decode("ascii"),
            "characteristics": hx(SECTION_CHARACTERISTICS),
            "header_file_offset": hx(plan.placement.header_offset),
            "raw_offset": hx(plan.placement.raw_offset),
            "raw_size": hx(plan.placement.raw_size),
            "rva": hx(plan.placement.rva),
            "virtual_size": hx(plan.placement.virtual_size),
            "size_of_image": hx(plan.placement.size_of_image),
            "string_alignment": 8,
        },
        "strings": strings,
        "direct_references": direct_refs,
        "pointer_references": pointer_refs,
        "reference_exceptions": exceptions,
        "validations": validation,
    }


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_runtime_ui(scope: str, install: bool) -> dict:
    if install and game_is_running():
        raise SystemExit("ERROR: the game is running; no backup, build, or install was performed")
    packed_source = select_packed_source(require_backup=install)
    unpacked_path, unpack_details = unpack_packed_source(packed_source)
    clean_data = unpacked_path.read_bytes()
    if digest_bytes(clean_data) != UNPACKED_SHA256:
        raise ValueError("clean unpacked EXE hash changed after verification")

    config = load_canonical()
    canonical_validation = validate_canonical(config, clean_data)
    selected = select_scope_rows(config, scope)
    semantic = semantic_rows(selected)
    plan = prepare_build_plan(clean_data, semantic)
    built_data = build_image(clean_data, plan)

    ARTIFACT_EXE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ARTIFACT_EXE.with_name(ARTIFACT_EXE.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        temporary.write_bytes(built_data)
        validation = validate_artifact(clean_data, temporary, plan, config["entries"])
        artifact_hash = digest_file(temporary)
        os.replace(temporary, ARTIFACT_EXE)
    finally:
        if temporary.exists():
            temporary.unlink()
    if digest_file(ARTIFACT_EXE) != artifact_hash:
        raise ValueError("artifact hash changed after finalization")

    receipt = build_receipt(
        scope=scope,
        config=config,
        canonical_validation=canonical_validation,
        selected_rows=selected,
        plan=plan,
        packed_source=packed_source,
        unpack_details=unpack_details,
        artifact_path=ARTIFACT_EXE,
        validation=validation,
    )
    if install:
        installed_hash = install_artifact(artifact_hash=artifact_hash)
        receipt["installed"] = str(INSTALLED_EXE)
        receipt["installed_sha256"] = "sha256:" + installed_hash
    write_json_atomic(RECEIPT_PATH, receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("options", "core", "first_wave", "interface", "all"), default="first_wave")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true")
    action.add_argument("--restore-installed", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.restore_installed:
        restored_hash = restore_installed()
        print(json.dumps({
            "restored": str(INSTALLED_EXE),
            "sha256": "sha256:" + restored_hash,
        }, indent=2))
        return
    receipt = build_runtime_ui(args.scope, args.install)
    summary = {
        "scope": receipt["scope"],
        "artifact": receipt["artifact"],
        "artifact_sha256": receipt["artifact_sha256"],
        "counts": receipt["counts"],
        "new_section": receipt["new_section"],
    }
    if "installed_sha256" in receipt:
        summary["installed_sha256"] = receipt["installed_sha256"]
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
