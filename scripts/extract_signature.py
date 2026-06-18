#!/usr/bin/env python3
"""Extract a card autograph as black-on-transparent PNG.

Usage:
    extract_signature.py INPUT [-o OUTPUT] [--ink auto|blue|black|red|silver|gold]
                              [--bbox X1,Y1,X2,Y2]

If --bbox is omitted, scans the bottom 35% of the image (where the signature
strip lives on slabbed cards) and picks the largest connected colored region.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

INK_PROFILES = {
    # name: (R_target, G_target, B_target, distance_threshold)
    "blue":   (10,  80, 230, 90),
    "black":  (20,  20,  20, 70),
    "red":    (200, 30,  30, 90),
    "silver": (180, 180, 190, 60),
    "gold":   (200, 160, 40,  80),
}


def auto_detect_ink(arr: np.ndarray) -> str:
    """Pick the most likely ink color.

    Strategy: ink is high-saturation against the off-white signature box.
    We score by directional signals (blue-minus-red, red-minus-others, darkness)
    rather than nearest-color, since holographic patterns can leak silver/gold
    candidates that aren't real ink.
    """
    R = arr[..., 0].astype(np.int32)
    G = arr[..., 1].astype(np.int32)
    B = arr[..., 2].astype(np.int32)

    blue_score = int(np.maximum(0, B - np.maximum(R, G) - 25).sum())
    red_score = int(np.maximum(0, R - np.maximum(G, B) - 25).sum())
    lum = (R + G + B) // 3
    sat = np.max(arr, axis=-1).astype(np.int32) - np.min(arr, axis=-1).astype(np.int32)
    # "Black" = dark AND low saturation (so we don't grab dark blue)
    black_score = int(((lum < 80) & (sat < 30)).sum())

    scores = {"blue": blue_score, "red": red_score, "black": black_score}
    best = max(scores, key=scores.get)
    # If nothing wins meaningfully, fall back to black
    if scores[best] < 500:
        return "black"
    return best


def build_alpha(arr: np.ndarray, ink: str) -> np.ndarray:
    """Return alpha channel (0..255) where ink pixels are opaque."""
    R = arr[..., 0].astype(np.int32)
    G = arr[..., 1].astype(np.int32)
    B = arr[..., 2].astype(np.int32)

    if ink == "blue":
        signal = B - np.maximum(R, G)
        alpha = np.clip((signal - 20) * 6, 0, 255)
    elif ink == "red":
        signal = R - np.maximum(G, B)
        alpha = np.clip((signal - 20) * 6, 0, 255)
    elif ink == "black":
        lum = (R + G + B) // 3
        sat = np.max(arr, axis=-1).astype(np.int32) - np.min(arr, axis=-1).astype(np.int32)
        # Dark AND low saturation
        score = (100 - lum) - np.maximum(0, sat - 25) * 2
        alpha = np.clip(score * 4, 0, 255)
    elif ink == "silver":
        lum = (R + G + B) // 3
        sat = np.max(arr, axis=-1).astype(np.int32) - np.min(arr, axis=-1).astype(np.int32)
        # Mid-luminance, low-saturation
        alpha = np.clip((130 - np.abs(lum - 150)) - sat * 2, 0, 255)
    elif ink == "gold":
        signal = np.minimum(R, G) - B
        alpha = np.clip((signal - 30) * 5, 0, 255)
    else:
        alpha = np.zeros_like(R)

    return alpha.astype(np.uint8)


def find_signature_box(arr: np.ndarray) -> tuple[int, int, int, int] | None:
    """Find the white/cream signature box on a slabbed card.

    Cards print the autograph on a near-white sticker that contrasts with the
    holographic/dark card design. We look for the largest near-white rectangle
    in the lower half of the image.
    """
    h, w = arr.shape[:2]
    R = arr[..., 0].astype(np.int32)
    G = arr[..., 1].astype(np.int32)
    B = arr[..., 2].astype(np.int32)
    sat = np.max(arr, axis=-1).astype(np.int32) - np.min(arr, axis=-1).astype(np.int32)
    lum = (R + G + B) // 3
    whitish = (lum > 180) & (sat < 40)

    # Restrict to lower 60% of card
    top_limit = int(h * 0.4)
    whitish[:top_limit] = False

    # Per-row whiteness density
    row_density = whitish.sum(axis=1) / w
    # Rows that are at least 30% white belong to a candidate box
    box_rows = np.where(row_density > 0.3)[0]
    if len(box_rows) < 20:
        return None

    # Find the longest contiguous run
    runs = []
    start = box_rows[0]
    prev = box_rows[0]
    for r in box_rows[1:]:
        if r - prev > 5:
            runs.append((start, prev))
            start = r
        prev = r
    runs.append((start, prev))
    y1, y2 = max(runs, key=lambda r: r[1] - r[0])
    if y2 - y1 < 30:
        return None

    # Within those rows, find columns that are mostly white
    col_density = whitish[y1:y2 + 1].sum(axis=0) / (y2 - y1 + 1)
    box_cols = np.where(col_density > 0.4)[0]
    if len(box_cols) < 20:
        return None
    runs = []
    start = box_cols[0]
    prev = box_cols[0]
    for c in box_cols[1:]:
        if c - prev > 8:
            runs.append((start, prev))
            start = c
        prev = c
    runs.append((start, prev))
    x1, x2 = max(runs, key=lambda r: r[1] - r[0])

    return (int(x1), int(y1), int(x2), int(y2))


def _ink_bbox_in_region(arr: np.ndarray, ink: str, y_offset: int = 0
                        ) -> tuple[int, int, int, int] | None:
    alpha = build_alpha(arr, ink)
    mask = alpha > 80
    if mask.sum() < 80:
        return None
    ys, xs = np.where(mask)
    pad = 20
    h, w = arr.shape[:2]
    return (max(0, int(xs.min()) - pad),
            max(0, int(ys.min()) - pad) + y_offset,
            min(w, int(xs.max()) + pad),
            min(h, int(ys.max()) + pad) + y_offset)


def find_signature_region(arr: np.ndarray, ink: str) -> tuple[int, int, int, int]:
    """Locate signature ink. Prefers the autograph box; falls back to bottom strip."""
    box = find_signature_box(arr)
    if box is not None:
        x1, y1, x2, y2 = box
        pad_in = 4
        cand = (x1 + pad_in, y1 + pad_in, x2 - pad_in, y2 - pad_in)
        # Verify there's actual ink inside; otherwise fall through to bottom-strip search
        sub = arr[cand[1]:cand[3], cand[0]:cand[2]]
        if (build_alpha(sub, ink) > 80).sum() >= 50:
            return cand

    h, w = arr.shape[:2]
    # Try bottom 50% (covers on-card sigs that sit mid-lower)
    for top_frac in (0.55, 0.40):
        top = int(h * top_frac)
        strip = arr[top:, :]
        bb = _ink_bbox_in_region(strip, ink, y_offset=top)
        if bb is not None:
            return bb

    return (0, h // 2, w, h)


def extract(input_path: Path, output_path: Path, ink: str, bbox: tuple | None) -> dict:
    img = Image.open(input_path).convert("RGB")
    arr = np.array(img)

    if ink == "auto":
        # Detect on bottom strip where ink lives
        h = arr.shape[0]
        ink = auto_detect_ink(arr[int(h * 0.65):, :])

    if bbox is None:
        bbox = find_signature_region(arr, ink)
    x1, y1, x2, y2 = bbox

    crop = arr[y1:y2, x1:x2]
    alpha = build_alpha(crop, ink)

    h, w = alpha.shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., 3] = alpha  # black RGB defaults to 0

    out_img = Image.fromarray(out)
    # Trim transparent borders with small pad
    bbox2 = out_img.getbbox()
    if bbox2 is not None:
        pad = 20
        l, t, r, b = bbox2
        out_img = out_img.crop((max(0, l - pad), max(0, t - pad),
                                min(w, r + pad), min(h, b + pad)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(output_path)
    return {"ink": ink, "bbox": bbox, "out_size": out_img.size, "path": str(output_path)}


def parse_bbox(s: str) -> tuple[int, int, int, int]:
    parts = [int(x) for x in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be X1,Y1,X2,Y2")
    return tuple(parts)  # type: ignore[return-value]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--ink", default="auto",
                   choices=["auto"] + list(INK_PROFILES.keys()))
    p.add_argument("--bbox", type=parse_bbox, default=None,
                   help="Override autodetect: X1,Y1,X2,Y2 in pixels")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    info = extract(args.input, args.output, args.ink, args.bbox)
    if not args.quiet:
        print(f"ink={info['ink']} bbox={info['bbox']} -> {info['path']} ({info['out_size'][0]}x{info['out_size'][1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
