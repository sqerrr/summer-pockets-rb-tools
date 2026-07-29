# SiglusEngine format reference

Verified against Summer Pockets REFLECTION BLUE, SiglusEngine 1.1.134.
All offsets are little-endian. Reference implementations: `_tools/siglus.py`
(Python) and `SPTranslate/uSiglus.pas` (Delphi, production).

## Scene.pck header

`0x5C` bytes: one dword holding the header size, then ten `(offset, count)`
pairs. Only the last four pairs matter for text.

| Pair | Offset field | Content |
|------|--------------|---------|
| 1-3  | 0x04, 0x0C, 0x14 | global variable types, name index, name data |
| 4-6  | 0x1C, 0x24, 0x2C | function addresses, name index, name data |
| 7    | 0x34 | scene name index, `(charOffset, charLength)` per scene; names follow inline |
| 8    | 0x3C | second copy of the scene names |
| 9    | 0x44 | scene data index, `(offset, size)` per scene |
| 10   | 0x4C | scene blobs, offsets relative to this field |

## Scene blob

1. XOR with a 256-byte key, index `i mod 256`. The key lives in `.rdata` at
   VA `0x00ADABB0` of the unpacked `SiglusEngine.exe` and starts with
   `70 F8 A6 B0 A1 A5 28 4F`. Extract it rather than hardcoding a copy.
2. LZSS, taken from `sub_71CE90`:

```text
dword compressed_size   (whole blob, including these 8 bytes)
dword raw_size
loop:
    flag byte, least significant bit first, eight operations per byte
    bit 1 -> copy one literal byte
    bit 0 -> read word w
             offset = w shr 4
             count  = (w and 0x0F) + 2
             copy count bytes from dst[dp - offset], one byte at a time
```

Blocks overlap, so the copy must stay byte-by-byte. A block memory move
produces silently wrong output.

## Scene body

132-byte header: one dword size, then sixteen `(offset, count)` pairs.

| Pair | Content |
|------|---------|
| 1 | bytecode offset and length |
| 2 | string index, `(charOffset, charLength)` per entry |
| 3 | string data, UTF-16LE |
| 4-16 | labels, z-labels, command and property tables |

Each string is obfuscated per 16-bit unit:

```text
key = (stringIndex * 0x7087) and 0xFFFF
plain[i] = stored[i] xor key
```

## Rebuild invariants

Verified across all 517 scenes:

- the string index is immediately followed by the string data;
- the string pool is the last region of the scene, followed by two tail bytes;
- character offsets are strictly sequential with no gaps.

Rebuilding therefore means: keep everything before the string index untouched,
write a new index and new data, re-append the tail. The string count must not
change, because the bytecode addresses strings by index. Lengths may change
freely.

A literal-only LZ stream (`0xFF` flag plus eight literal bytes) is valid input
for the decompressor. It costs about 12.5% over the raw size, which means the
pack grows from 30 MB to 76 MB because the original compression is dropped.

## Character width

The engine gives a character a full-width cell exactly when the character
encodes to two bytes in Shift-JIS. Font metrics are ignored: setting the advance
of Latin `W` to 1024 and `M` to 256 changed nothing on screen.

| Range | Shift-JIS | Cell |
|-------|-----------|------|
| ASCII | one byte | half |
| Latin-1 Supplement | absent, except `¢ £ § ¨ ¬ ° ± ´ ¶ × ÷` | half |
| Latin Extended-A | absent entirely | half |
| Greek, Cyrillic | present, JIS X 0208 rows 6-7 | full |
| Kana, kanji | present | full |

## Russian carrier encoding

Russian is stored as Latin Extended-A codepoints, which are absent from
Shift-JIS and therefore keep the half-width cell. The font maps those
codepoints to the Cyrillic outlines.

```text
U+0100..U+011F  ->  А..Я  without Ё
U+0120          ->  Ё
U+0121..U+0140  ->  а..я  without ё
U+0141          ->  ё
```

Implemented by `EncodeRussian` and `DecodeRussian` in `uSiglus.pas`, mirrored by
`_tools/encode_ru.py`. Any change to the table must be applied to the font
builder, both codecs and any already built `Scene.pck` at the same time.

Punctuation notes:

- `«` `»` `—` `–` have no glyphs in the stock fonts;
- guillemets are produced by condensing `《》` (U+300A/U+300B);
- `—` and `–` are substituted with `―` (U+2015), which exists and reads as a
  long dash;
- `…` (U+2026) exists but is full-width, which is acceptable.

## Fonts

`dat/font01.ttf` (MotoyaLMaru) and `dat/font02.ttf` (MotoyaLCedar), 1024 units
per em. Latin is monospaced at 512 units. Cyrillic outlines are drawn full
width, up to 905 units of ink, and must be condensed to about 470 to fit a
half-width cell. Cap height already matches Latin (782 against 781), so only
horizontal scaling is needed. No Cyrillic glyph is composite, so the transform
is safe.

Built by `_tools/build_font.py`, always from `font01.ttf.orig` and
`font02.ttf.orig`, so the operation is idempotent.

## Not yet analysed

- `Gameexe.dat` uses a different encryption; needed only to change text window
  geometry.
- `dat/*.dbs` hold CG gallery, music and minigame text, roughly 15 000 Japanese
  characters.
