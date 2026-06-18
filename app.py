"""Card Detective — daily zoom-and-guess card recognition game.

Concept ref: https://betfanatics.atlassian.net/wiki/spaces/FAN/pages/3169222921 (Concept 2)

The puzzle: a tight crop of a real Fanatics Collect listing — eye, jersey
number, helmet logo, patch swatch — and the user guesses the player. Each
wrong guess pulls the camera back one notch until the full card is visible.
Reveal links to the live Collect listing.

The actual zooming is implemented client-side as CSS transform:scale on the
card image with transform-origin set from each card's curated focal point —
no per-zoom image assets, just one source photo per card.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

app = Flask(__name__, static_folder="static")

DATA_PATH = Path(__file__).parent / "data" / "cards.json"
EPOCH = dt.date(2026, 1, 1)
ZOOM_RUNGS = 5  # 1 starting crop + 4 progressive zoom-outs


def load_cards() -> list[dict]:
    return json.loads(DATA_PATH.read_text())


def card_for_date(d: dt.date) -> dict:
    cards = load_cards()
    days = (d - EPOCH).days
    return cards[days % len(cards)]


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


COMMON_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def name_tokens(name: str) -> list[str]:
    return [t for t in normalize(name).split() if t not in COMMON_SUFFIXES]


def is_match(guess: str, canonical: str) -> bool:
    g = name_tokens(guess)
    c = name_tokens(canonical)
    if not g:
        return False
    if g[-1] not in c and not any(t.startswith(g[-1]) for t in c):
        return False
    if len(g) > 1:
        if g[0] not in c and not any(t.startswith(g[0]) for t in c):
            return False
    return True


def public_card_for_attempts(card: dict, attempts: int) -> dict:
    return {
        "id": card["listing_id"],
        "card_path": card["card_path"],
        "focal": card["focal"],
        "detail_label": card["detail_label"],
        "max_attempts": ZOOM_RUNGS,
        "attempts": attempts,
        "zoom_rung": min(attempts, ZOOM_RUNGS - 1),
    }


def reveal_card(card: dict) -> dict:
    return {
        "id": card["listing_id"],
        "player": card["player"],
        "sport": card["sport"],
        "era": card["era"],
        "team": card["team"],
        "position": card["position"],
        "story": card["story"],
        "card_path": card["card_path"],
        "title": card.get("title"),
        "year": card.get("year"),
        "listing_url": card.get("listing_url"),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/today")
def today():
    card = card_for_date(dt.date.today())
    attempts = int(request.args.get("attempts", 0))
    return jsonify(public_card_for_attempts(card, attempts))


@app.route("/api/guess", methods=["POST"])
def guess():
    payload = request.get_json(force=True) or {}
    guess_text = (payload.get("guess") or "").strip()
    attempts = int(payload.get("attempts", 0))
    card = card_for_date(dt.date.today())
    correct = bool(guess_text) and is_match(guess_text, card["player"])
    new_attempts = attempts + 1

    if correct or new_attempts >= ZOOM_RUNGS:
        return jsonify({
            "correct": correct,
            "done": True,
            "attempts": new_attempts,
            "reveal": reveal_card(card),
        })

    return jsonify({
        "correct": False,
        "done": False,
        "attempts": new_attempts,
        "zoom_rung": min(new_attempts, ZOOM_RUNGS - 1),
    })


@app.route("/static/<path:p>")
def static_file(p):
    return send_from_directory(app.static_folder, p)


if __name__ == "__main__":
    app.run(debug=True, port=5051)
