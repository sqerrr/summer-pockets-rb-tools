"""Builds the game fonts for Russian.

The engine decides cell width by Shift-JIS: two bytes -> full width. Cyrillic is
in JIS X 0208, so it always gets an ideograph-sized cell no matter what the font
says. Latin Extended-A has no Shift-JIS representation at all, so those
codepoints stay half-width and are used to carry Russian.

Layout (matches EncodeRussian/DecodeRussian in uSiglus.pas):
    U+0100..U+011F  ->  А..Я  (without Ё)
    U+0120          ->  Ё
    U+0121..U+0140  ->  а..я  (without ё)
    U+0141          ->  ё

Cyrillic outlines are also condensed horizontally, because they are drawn as
full-width designs and would otherwise overflow a half-width cell.
"""
import os, shutil, sys
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Transform

DAT = r"A:\Projects\Summer Pockets REFLECTION BLUE\dat"
HALF = 512
INK_BUDGET = 470


def carrier_map():
    m = {}
    for i in range(32):
        m[0x100 + i] = 0x410 + i
    m[0x120] = 0x401
    for i in range(32):
        m[0x121 + i] = 0x430 + i
    m[0x141] = 0x451
    return m


CARRIERS = carrier_map()

# Russian guillemets are absent from these Japanese fonts. Borrow the CJK double
# angle brackets and condense them the same way as the letters.
BORROW = {0x00AB: 0x300A, 0x00BB: 0x300B}


def build(name):
    src = os.path.join(DAT, name)
    bak = src + ".orig"
    if not os.path.exists(bak):
        shutil.copy2(src, bak)

    f = TTFont(bak)
    glyf, hmtx, gs = f["glyf"], f["hmtx"], f.getGlyphSet()
    cmap = f.getBestCmap()

    missing = [hex(c) for c in set(CARRIERS.values()) if c not in cmap]
    if missing:
        sys.exit("font %s lacks cyrillic glyphs: %s" % (name, missing))

    # condense every cyrillic outline into the half-width box
    built = {}
    widest = 0
    for cp in sorted(set(CARRIERS.values())):
        g = cmap[cp]
        bp = BoundsPen(gs)
        gs[g].draw(bp)
        if bp.bounds is None:
            continue
        x0, _, x1, _ = bp.bounds
        ink = x1 - x0
        k = min(1.0, INK_BUDGET / ink) if ink > 0 else 1.0
        dx = (HALF - ink * k) / 2.0 - x0 * k
        pen = TTGlyphPen(gs)
        gs[g].draw(TransformPen(pen, Transform(k, 0, 0, 1, dx, 0)))
        built[g] = (pen.glyph(), round(x0 * k + dx))
        widest = max(widest, ink * k)

    for g, (gl, lsb) in built.items():
        glyf[g] = gl
        gl.recalcBounds(glyf)
        hmtx[g] = (HALF, lsb)

    # point the carrier codepoints at those glyphs
    for carrier, cyr in CARRIERS.items():
        gname = cmap[cyr]
        for t in f["cmap"].tables:
            if t.isUnicode():
                t.cmap[carrier] = gname

    # build half-width guillemets from the CJK double angle brackets
    borrowed = 0
    for want, donor in BORROW.items():
        if want in cmap or donor not in cmap:
            continue
        dg = cmap[donor]
        bp = BoundsPen(gs)
        gs[dg].draw(bp)
        if bp.bounds is None:
            continue
        x0, _, x1, _ = bp.bounds
        ink = x1 - x0
        k = min(1.0, (INK_BUDGET * 0.62) / ink) if ink > 0 else 1.0
        dx = (HALF - ink * k) / 2.0 - x0 * k
        pen = TTGlyphPen(gs)
        gs[dg].draw(TransformPen(pen, Transform(k, 0, 0, 1, dx, 0)))
        # condense the donor in place and point the guillemet at it; no new
        # glyph is created, which keeps the glyph order untouched
        glyf[dg] = pen.glyph()
        glyf[dg].recalcBounds(glyf)
        hmtx[dg] = (HALF, round(x0 * k + dx))
        for t in f["cmap"].tables:
            if t.isUnicode():
                t.cmap[want] = dg
        borrowed += 1

    f.save(src)
    f.close()
    return len(CARRIERS), round(widest), borrowed


for fn in ("font01.ttf", "font02.ttf"):
    n, w, b = build(fn)
    print("%s: %d carriers, widest ink %d/%d, guillemets added %d"
          % (fn, n, w, HALF, b))

print("\nverification (carrier -> glyph must equal cyrillic -> glyph):")
for fn in ("font01.ttf", "font02.ttf"):
    f = TTFont(os.path.join(DAT, fn))
    c = f.getBestCmap()
    ok = all(c.get(k) == c.get(v) for k, v in CARRIERS.items())
    latin_ok = c.get(ord("A")) != c.get(0x410) and c.get(ord("e")) is not None
    print("  %s carriers=%s  latin untouched=%s" % (fn, ok, latin_ok))
    f.close()
