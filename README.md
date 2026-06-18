# Card Detective

Functional prototype of the **Card Detective** game concept — a daily zoom-and-guess card-recognition game for the FanApp x Fanatics Collect FTP funnel. Concept doc: [New Collect FTP Game Concepts](https://betfanatics.atlassian.net/wiki/spaces/FAN/pages/3169222921), Concept 2.

The user opens to a tight square crop of a real Fanatics Collect listing — an eye, a jersey number, a patch swatch — and guesses the player. Each wrong guess pulls the camera back one notch until the full card is visible. The reveal screen shows the actual graded card with a "Bid on Collect" CTA.

This is the cheapest follow-on to [Mystery Signature](https://github.com/alowenthal-fbg/mystery-signature) — same image-crop infrastructure, different mechanic.

## How it works end-to-end

1. **Inventory source** — same Fanatics Collect Algolia scraper as Mystery Signature (`scripts/scrape_cards.py`). The `data/cards.json` here uses the same 10 curated listings.
2. **Curated focal points** — for each card, a hand-picked normalized `{x, y}` focal point and a `detail_label` (e.g. "Jersey number", "Patch swatch", "Eye") that hints at what's being shown at the tightest zoom.
3. **Client-side zoom mechanic** — the card image is rendered in a square viewport with `object-fit: cover`. Each zoom rung is a `transform: scale + transform-origin` against that single image — no per-zoom image assets, just one source photo per card. Rungs: `[10×, 5×, 3×, 1.8×, 1.0×]`.
4. **Today's card** is selected deterministically from the date so all users see the same puzzle.

## Run it locally

```bash
pip install -r requirements.txt
python3 app.py
# → open http://127.0.0.1:5051
```

## Static build (for GitHub Pages)

The `docs/` directory is a fully static port of the same game. Date-keyed selection and guess validation run client-side. Push and enable GitHub Pages from `main /docs`.

## Repo layout

```
card_detective/
├── app.py                    # Flask backend
├── templates/index.html      # Single-page UI
├── static/
│   ├── style.css
│   ├── app.js
│   └── cards/<id>.jpg        # full card photos (slab labels cropped out)
├── data/cards.json           # curated dataset with focal points + detail labels
├── docs/                     # static port for GitHub Pages
├── scripts/
│   ├── scrape_cards.py       # Fanatics Collect Algolia scraper (vendored from Mystery Signature)
│   ├── extract_signature.py
│   ├── run_batch.py
│   └── crop_slab.py          # one-time crop of PSA/BGS slab labels
├── requirements.txt
└── README.md
```

## Dataset notes

Card images were copied from the Mystery Signature repo and post-processed with `scripts/crop_slab.py` to remove the PSA/BGS slab top label and barcode strip — otherwise those would tip off the answer at mid-zoom. The bottom of the slab (which often shows the player name printed below the card) is left in place because it only becomes legible at the final "Full card" rung, after the user has had four guesses.

## Known limitations

- **Focal points are hand-picked**, not auto-generated. The concept doc calls out that production needs a difficulty model — some crops will be too easy (cap logo gives the team in one frame) or too hard (a generic patch). This prototype lets a curator set a focal point + label per card.
- **No CV crop generation**. Production version would use the same image-crop infrastructure as Mystery Signature plus a player-detector model to pick "interesting square" crops automatically. Here, we use one focal point per card and let CSS scale do the work.
- **The PSA slab top edge** has been cropped, but the slab side rails are still visible in the full-card view — that's intentional, since this is meant to be sourced from real authenticated Collect listings. Production should source from authenticated/graded marketplace listings only.

## API (Flask version)

- `GET /api/today?attempts=N` — returns today's puzzle state at attempt count `N`. Includes the card path, focal point, detail label, and current zoom rung.
- `POST /api/guess` body `{"guess": "...", "attempts": N}` — validates against canonical player name (accent/suffix-aware fuzzy match). Returns either the new zoom rung or the reveal payload.

## Concept rules summary (from the doc)

> Pure visual recognition mechanic that requires no collectibles vocabulary. The game showcases the photography and craft of cards themselves — uniforms, logos, on-card details — which is exactly the aesthetic hook for lapsed collectors who remember _looking_ at cards.
