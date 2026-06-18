#!/usr/bin/env python3
"""Crop the PSA/BGS slab label and bottom barcode out of card images so the
in-card content is what the zoom-out mechanic operates on. Run once after
copying images from ~/mystery_signature/docs/cards/."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

# Tuned by eye against the 10 Mystery Signature cards. Slab label is the top
# ~14%; the barcode strip below the slab adds another ~3%. Bottom is clean.
TOP_CROP = 0.155
BOTTOM_CROP = 0.0


def crop_one(path: Path) -> None:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    top = int(h * TOP_CROP)
    bottom = h - int(h * BOTTOM_CROP)
    cropped = img.crop((0, top, w, bottom))
    cropped.save(path, quality=92)
    print(f"  {path.name}  {w}x{h} -> {cropped.size[0]}x{cropped.size[1]}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: crop_slab.py <dir> [<dir>...]")
        return 2
    for d in argv[1:]:
        p = Path(d)
        if not p.is_dir():
            print(f"skip {p} (not a dir)")
            continue
        print(f"cropping {p}")
        for img in sorted(p.glob("*.jpg")):
            crop_one(img)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
