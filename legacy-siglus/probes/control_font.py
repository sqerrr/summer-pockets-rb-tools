"""Control experiment: does the engine honour hmtx advance widths at all?

Cyrillic keeps the half-width patch (advance 512). On top of that two Latin
letters get deliberately wrong advances without touching their outlines:
    W -> 1024  (should become widely spaced if the engine reads the font)
    M ->  256  (should collide with its neighbour for the same reason)
Everything else is left alone, so the rendered line answers the question.
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
PROBES = {"W": 1024, "M": 256}


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

    probe_report = []
    for ch, adv in PROBES.items():
        g = cmap.get(ord(ch))
        old = hmtx[g][0]
        hmtx[g] = (adv, hmtx[g][1])
        probe_report.append(f"{ch}: {old} -> {adv}")

    f.save(src)
    f.close()
    return probe_report


for fn in ("font01.ttf", "font02.ttf"):
    print(fn, "|", ", ".join(patch(fn)))

print("\nverification:")
for fn in ("font01.ttf", "font02.ttf"):
    f = TTFont(os.path.join(DAT, fn))
    cmap, hmtx = f.getBestCmap(), f["hmtx"]
    print(" ", fn, " ".join(
        f"{c}={hmtx[cmap[ord(c)]][0]}" for c in "WMQBXЖШПро"))
    f.close()
