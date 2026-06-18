#!/usr/bin/env python3
"""Batch-extract signatures from many cards.

Two input modes:

  1) Local folder of card images:
        run_batch.py --folder ~/Pictures/cards --out ~/card_sigs

     Player labels can be supplied via:
       - sidecar `<image>.player.txt` containing the player's name
       - `--labels labels.csv` (columns: filename,player)
       - none → output goes to ~/card_sigs/_unlabeled/

  2) JSON manifest from scrape_cards.py (with --download already applied):
        scrape_cards.py URL --download cards/ --manifest cards/manifest.json
        run_batch.py --manifest cards/manifest.json --out ~/card_sigs

     Player labels are auto-extracted from each entry's title using
     extract_player_from_title().

Outputs:
   <out>/<player_slug>/<basename>.png        # signatures
   <out>/manifest.csv                        # full record per card
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EXTRACT_SIG = SCRIPT_DIR / "extract_signature.py"

# Tokens commonly found in card titles that aren't the player name.
# Anything matching is stripped during heuristic player extraction.
NOISE_TOKENS = {
    "auto", "autograph", "autographs", "rookie", "rc", "psa", "bgs", "sgc",
    "cgc", "dna", "patch", "jersey", "relic", "1of1", "ssp", "sp",
    "mint", "gem", "holo", "refractor", "prizm", "mosaic", "select",
    "optic", "donruss", "topps", "panini", "bowman", "fleer", "upper", "deck",
    "chrome", "pokemon", "yu-gi-oh", "yugioh", "magic", "mtg", "ex",
    "pop", "population", "graded", "higher", "none", "lot",
    "blue", "red", "green", "gold", "silver", "black", "purple", "orange",
    "pink", "white", "rainbow", "ruby", "emerald", "sapphire", "diamond",
    "edition", "1st", "first", "limited", "rare", "ultra", "super",
    "score", "final", "game", "big", "set", "logo",
}

# Words that anchor the END of a player name in a card title — the player's
# name is typically the last 1–4 capitalized tokens before one of these.
ANCHOR_TOKENS = {
    "auto", "autograph", "autographs", "autographed", "patch", "rookie",
    "rc", "jersey", "relic", "signed", "signature", "cut",
}

PLAYER_NAME_TOKEN = re.compile(r"^[A-Z][A-Za-z'\-.]*$")


def extract_player_from_title(title: str) -> str | None:
    """Find the proper-noun run that precedes the first AUTO/PATCH/etc. anchor."""
    if not title:
        return None
    # Tokenize, preserving apostrophes and hyphens
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-.]*|\d+", title)
    # Find first anchor index
    anchor_idx = None
    for i, tok in enumerate(tokens):
        if tok.lower() in ANCHOR_TOKENS:
            anchor_idx = i
            break

    # Walk backwards from anchor (or end of title) collecting Capitalized tokens
    end = anchor_idx if anchor_idx is not None else len(tokens)
    name: list[str] = []
    for tok in reversed(tokens[:end]):
        if PLAYER_NAME_TOKEN.match(tok) and tok.lower() not in NOISE_TOKENS:
            name.append(tok)
            if len(name) >= 4:
                break
        else:
            if name:
                break
    if not name:
        return None
    name.reverse()
    # Require at least 2 tokens for a real player name; otherwise fall back to
    # the longest capitalized run anywhere in the title (drops single-name hits)
    if len(name) >= 2:
        return " ".join(name)

    # Fallback: longest run of Capitalized non-noise tokens anywhere
    runs: list[list[str]] = []
    cur: list[str] = []
    for tok in tokens:
        if PLAYER_NAME_TOKEN.match(tok) and tok.lower() not in NOISE_TOKENS:
            cur.append(tok)
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    if runs:
        return " ".join(max(runs, key=len))
    return name[0] if name else None


SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def slugify(s: str) -> str:
    s = SLUG_RE.sub("-", s).strip("-").lower()
    return s or "unknown"


def run_extract(input_path: Path, output_path: Path) -> tuple[bool, str]:
    try:
        out = subprocess.run(
            [sys.executable, str(EXTRACT_SIG), str(input_path),
             "-o", str(output_path), "--quiet"],
            check=True, capture_output=True, text=True,
        )
        return True, out.stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or e.stdout or str(e)).strip()


def gather_from_folder(folder: Path, labels: dict[str, str]) -> list[dict]:
    entries = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        # Sidecar .player.txt overrides labels.csv
        sidecar = path.with_suffix(path.suffix + ".player.txt")
        if not sidecar.exists():
            sidecar = path.with_name(path.stem + ".player.txt")
        if sidecar.exists():
            player = sidecar.read_text().strip()
        else:
            player = labels.get(path.name) or labels.get(path.stem) or ""
        entries.append({
            "image_path": str(path),
            "player": player,
            "title": path.stem,
        })
    return entries


def gather_from_manifest(manifest_path: Path) -> list[dict]:
    data = json.loads(manifest_path.read_text())
    entries = []
    for item in data:
        img = item.get("image_path")
        if not img:
            continue
        title = item.get("title") or ""
        entries.append({
            "image_path": img,
            "title": title,
            "player": item.get("player") or extract_player_from_title(title) or "",
            "listing_id": item.get("listing_id"),
            "listing_url": item.get("listing_url"),
            "marketplace": item.get("marketplace"),
            "year": item.get("year"),
        })
    return entries


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--folder", type=Path, help="Folder of card images")
    src.add_argument("--manifest", type=Path,
                     help="JSON manifest from scrape_cards.py --download")
    p.add_argument("--out", type=Path, required=True,
                   help="Output root (will create <out>/<player_slug>/...)")
    p.add_argument("--labels", type=Path, default=None,
                   help="CSV with columns filename,player (folder mode)")
    args = p.parse_args(argv)

    labels: dict[str, str] = {}
    if args.labels:
        with args.labels.open() as f:
            for row in csv.DictReader(f):
                labels[row["filename"]] = row["player"]

    if args.folder:
        entries = gather_from_folder(args.folder, labels)
    else:
        entries = gather_from_manifest(args.manifest)

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_csv = args.out / "manifest.csv"
    rows = []
    for e in entries:
        player = e.get("player") or "unlabeled"
        slug = slugify(player) if player != "unlabeled" else "_unlabeled"
        in_path = Path(e["image_path"])
        out_dir = args.out / slug
        out_path = out_dir / (in_path.stem + ".png")
        ok, info = run_extract(in_path, out_path)
        rows.append({
            "player": player,
            "input": str(in_path),
            "output": str(out_path) if ok else "",
            "title": e.get("title", ""),
            "listing_url": e.get("listing_url", ""),
            "ok": ok,
            "info": info,
        })
        status = "OK" if ok else "ERR"
        print(f"[{status}] {player or '?'}: {in_path.name} -> {out_path.relative_to(args.out)}",
              file=sys.stderr)

    with manifest_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["player", "input", "output", "title", "listing_url", "ok", "info"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nProcessed {len(rows)} cards. Manifest: {manifest_csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
