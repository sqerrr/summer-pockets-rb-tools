# Bootstrap checklist

## Repository audit

- [ ] Parser located
- [ ] Builder located
- [ ] Commands documented
- [ ] Dependencies documented
- [ ] Encoding identified
- [ ] Text/command distinction identified
- [ ] All internal language slots identified and aligned
- [ ] Canonical data separated from engine-specific encoding

## Round-trip

- [ ] Original parsed
- [ ] Unchanged text rebuilt
- [ ] File counts compared
- [ ] Segment counts compared
- [ ] Tags compared
- [ ] Choices/jumps checked
- [ ] Length-changing relocation and reference validation checked where needed
- [ ] Game starts
- [ ] Cyrillic smoke test completed

## Catalogue

- [ ] File IDs stable
- [ ] Scene IDs stable
- [ ] Segment IDs unique
- [ ] Speakers normalized
- [ ] Narrative segments represented
- [ ] Service strings separated
- [ ] Source hashes recorded where practical
- [ ] Source IDs do not depend on byte offsets or source text
