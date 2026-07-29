"""Experiment: the engine lays out by codepoint, ignoring font metrics.
So put Cyrillic outlines onto ASCII codepoints and see whether they get the
half-width cell that ASCII enjoys.

q -> Ж    w -> Ш    e -> Щ   (outlines condensed to fit a half-width cell)
Cyrillic codepoints are left in place, so one line can show both.
"""
import os, shutil
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Transform

DAT = r"A:\Projects\Summer Pockets REFLECTION BLUE\dat"
HALF, BUDGET = 512, 480
REMAP = {"q": "Ж", "w": "Ш", "e": "Щ"}


def patch(name):
    src = os.path.join(DAT, name)
    bak = src + ".orig"
    if not os.path.exists(bak):
        shutil.copy2(src, bak)

    f = TTFont(bak)
    glyf, hmtx, gs = f["glyf"], f["hmtx"], f.getGlyphSet()
    cmap = f.getBestCmap()

    # condense cyrillic into the half-width box (same as before)
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

    # point selected ASCII codepoints at the cyrillic glyphs
    report = []
    for ascii_ch, cyr_ch in REMAP.items():
        target = cmap[ord(cyr_ch)]
        for t in f["cmap"].tables:
            if t.isUnicode():
                t.cmap[ord(ascii_ch)] = target
        report.append(f"{ascii_ch} -> {cyr_ch} ({target})")

    f.save(src)
    f.close()
    return report


for fn in ("font01.ttf", "font02.ttf"):
    print(fn, "|", ", ".join(patch(fn)))

print("\nverification:")
for fn in ("font01.ttf", "font02.ttf"):
    f = TTFont(os.path.join(DAT, fn))
    c = f.getBestCmap()
    print(" ", fn, " ".join(f"{ch}={c[ord(ch)]}" for ch in "qweЖШЩA"))
    f.close()
