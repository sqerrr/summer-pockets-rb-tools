"""Which codepoint ranges does the engine treat as half-width?

Ж/Ш/Щ outlines are mapped onto probe codepoints in several ranges. Whatever
renders tightly in game is a usable carrier for Russian text.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths
import os, shutil
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Transform

DAT = str(paths.DAT_DIR)
HALF, BUDGET = 512, 480
SRC = "ЖШЩ"
PROBES = {
    "ascii":  (0x71, 0x77, 0x65),     # q w e
    "latin1": (0xE0, 0xE1, 0xE2),     # à á â
    "extA":   (0x100, 0x101, 0x102),  # Ā ā Ă
    "extB":   (0x180, 0x181, 0x182),  # ƀ Ɓ Ƃ
    "greek":  (0x3B1, 0x3B2, 0x3B3),  # α β γ
}


def patch(name):
    src = os.path.join(DAT, name)
    bak = src + ".orig"
    if not os.path.exists(bak):
        shutil.copy2(src, bak)
    f = TTFont(bak)
    glyf, hmtx, gs = f["glyf"], f["hmtx"], f.getGlyphSet()
    cmap = f.getBestCmap()

    built = {}
    for cp in sorted(c for c in cmap if 0x400 <= c <= 0x4FF):
        g = cmap[cp]
        bp = BoundsPen(gs)
        gs[g].draw(bp)
        if bp.bounds is None:
            built[g] = (None, HALF, 0)
            continue
        x0, _, x1, _ = bp.bounds
        ink = x1 - x0
        k = min(1.0, BUDGET / ink) if ink > 0 else 1.0
        dx = (HALF - ink * k) / 2.0 - x0 * k
        pen = TTGlyphPen(gs)
        gs[g].draw(TransformPen(pen, Transform(k, 0, 0, 1, dx, 0)))
        built[g] = (pen.glyph(), HALF, round(x0 * k + dx))
    for g, (gl, adv, lsb) in built.items():
        if gl is not None:
            glyf[g] = gl
            gl.recalcBounds(glyf)
        hmtx[g] = (adv, lsb)

    targets = [cmap[ord(ch)] for ch in SRC]
    for label, cps in PROBES.items():
        for cp, gname in zip(cps, targets):
            for t in f["cmap"].tables:
                if t.isUnicode():
                    t.cmap[cp] = gname
            if hmtx[gname][0] != HALF:
                hmtx[gname] = (HALF, hmtx[gname][1])
    f.save(src)
    f.close()


for fn in ("font01.ttf", "font02.ttf"):
    patch(fn)
    print("patched", fn)

line = " ".join(
    "".join(chr(c) for c in cps) + "=" + label for label, cps in PROBES.items())
print("\nMarker line to put into the scene:")
print(line)
open(str(Path(__file__).resolve().parent / "marker.txt"), "w", encoding="utf-8").write(line + " | ")
