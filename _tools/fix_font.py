"""Converts the Cyrillic block of the game fonts from full-width to half-width.

Cap height already matches the Latin design, so only horizontal metrics change:
glyphs wider than the half-width box are condensed to fit, narrower ones keep
their natural width (standard monospace practice), and the advance is set to
the same 512 units the Latin glyphs use.
"""
import os, shutil, sys
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Transform

DAT = r"A:\Projects\Summer Pockets REFLECTION BLUE\dat"
HALF_ADVANCE = 512
INK_BUDGET = 480          # max ink width allowed inside the half-width box


def patch(name):
    src = os.path.join(DAT, name)
    bak = src + ".orig"
    if not os.path.exists(bak):
        shutil.copy2(src, bak)
        print("  backup ->", os.path.basename(bak))

    f = TTFont(bak)
    glyf, hmtx = f["glyf"], f["hmtx"]
    gs = f.getGlyphSet()
    cmap = f.getBestCmap()

    targets = sorted(cp for cp in cmap if 0x400 <= cp <= 0x4FF)
    built = {}
    stats = []
    for cp in targets:
        gname = cmap[cp]
        bp = BoundsPen(gs)
        gs[gname].draw(bp)
        if bp.bounds is None:
            built[gname] = (None, HALF_ADVANCE, 0)
            continue
        x0, _, x1, _ = bp.bounds
        ink = x1 - x0
        k = min(1.0, INK_BUDGET / ink) if ink > 0 else 1.0
        # centre the condensed outline inside the half-width box
        new_ink = ink * k
        dx = (HALF_ADVANCE - new_ink) / 2.0 - x0 * k

        pen = TTGlyphPen(gs)
        gs[gname].draw(TransformPen(pen, Transform(k, 0, 0, 1, dx, 0)))
        g = pen.glyph()
        built[gname] = (g, HALF_ADVANCE, round(x0 * k + dx))
        stats.append((chr(cp), ink, round(new_ink), round(k, 2)))

    for gname, (g, adv, lsb) in built.items():
        if g is not None:
            glyf[gname] = g
            g.recalcBounds(glyf)
        hmtx[gname] = (adv, lsb)

    f.save(src)
    f.close()
    return stats


for fn in ("font01.ttf", "font02.ttf"):
    print("==", fn)
    st = patch(fn)
    print("  cyrillic glyphs patched:", len(st))
    for ch in "ЖШЩМоретА":
        for c, ink, new, k in st:
            if c == ch:
                print(f"    {c}: ink {ink} -> {new}  (scale {k})")
                break

# verify
print("\n--- verification ---")
for fn in ("font01.ttf", "font02.ttf"):
    f = TTFont(os.path.join(DAT, fn))
    cmap, hmtx = f.getBestCmap(), f["hmtx"]
    adv = {c: hmtx[cmap[c]][0] for c in ("A", "W", "П", "Ж", "ы", "あ")
           if ord(c) in cmap for c in [c]}
    row = []
    for ch in ("A", "W", "П", "Ж", "ы", "\u3042"):
        g = cmap.get(ord(ch))
        row.append(f"{ch}={hmtx[g][0]}")
    print(" ", fn, " ".join(row))
    f.close()
