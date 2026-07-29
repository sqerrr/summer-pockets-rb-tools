"""Evidence for the technical_tags gate: what markup lives inside scene strings.

Scans every scene of the pristine pack and reports occurrences of the
protected patterns from config/qa-rules.yaml, control characters, and the
length distribution of displayed lines.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths

import collections
import re

import yaml

paths.ensure_importable()
from siglus import ScenePack, Scene  # noqa: E402

rules = yaml.safe_load(open(paths.ROOT / "config" / "qa-rules.yaml", encoding="utf-8"))
patterns = [(p, re.compile(p)) for p in rules["protected_patterns"]]

pck = ScenePack(str(paths.SCENE_PCK_ORIG))
hits = collections.Counter()
samples: dict[str, list[str]] = {}
control = collections.Counter()
lengths: list[int] = []
total = 0

for i in range(pck.count):
    for s in Scene(pck.scene(i)).strings():
        total += 1
        for src, rx in patterns:
            for m in rx.findall(s):
                hits[src] += 1
                if len(samples.setdefault(src, [])) < 8:
                    samples[src].append(m if isinstance(m, str) else str(m))
        for ch in s:
            if ord(ch) < 0x20:
                control[hex(ord(ch))] += 1
        # displayed lines: anything with a space and a letter, see LooksLikeText
        if " " in s and any(c.isalpha() for c in s):
            lengths.append(len(s))

print(f"scenes: {pck.count}, strings: {total}")
print("\nprotected patterns:")
for src, _ in patterns:
    n = hits.get(src, 0)
    extra = f"   e.g. {samples[src][:6]}" if n else ""
    print(f"  {src:<24} {n:>7}{extra}")
print("\ncontrol characters inside strings:", dict(control) or "none")

if lengths:
    lengths.sort()
    def pct(p):
        return lengths[min(len(lengths) - 1, int(len(lengths) * p / 100))]
    print(f"\ntext-like strings: {len(lengths)}")
    print(f"  length  min {lengths[0]}  median {pct(50)}  p90 {pct(90)} "
          f" p99 {pct(99)}  max {lengths[-1]}")
