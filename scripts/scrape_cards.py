#!/usr/bin/env python3
"""Scrape card listings from a Fanatics Collect marketplace URL.

Reads ?type=, ?q=, &category=, &page= from the URL and queries the public
Algolia index that powers fanaticscollect.com (search API key fetched from
the public collectSearchKey GraphQL endpoint).

Outputs JSON manifest to stdout (one entry per listing) and optionally
downloads the primary image of each listing to a directory.

Manifest entry:
    {
      "title":        "2023 Mosaic Carlos Boozer Autograph Blue ...",
      "image_url":    "https://...",
      "listing_url":  "https://www.fanaticscollect.com/weekly-auctions/.../<slug>",
      "marketplace":  "WEEKLY",
      "year":         2023,
      "image_path":   "/path/to/downloaded/image.jpg"  // only with --download
    }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ALGOLIA_APP_ID = "3XT9C4X62I"
ALGOLIA_INDEX = "prod_item_state_v1"
GRAPHQL_URL = "https://app.fanaticscollect.com/graphql"
USER_AGENT = "Mozilla/5.0 (compatible; card-sig-scraper/1.0)"


def http_post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    body = json.dumps(payload).encode()
    h = {"content-type": "application/json", "user-agent": USER_AGENT}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"user-agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_search_key() -> str:
    resp = http_post_json(
        GRAPHQL_URL,
        {"operationName": "webSearchKeyQuery",
         "query": "query webSearchKeyQuery { collectSearchKey }"},
        headers={"origin": "https://www.fanaticscollect.com",
                 "referer": "https://www.fanaticscollect.com/"},
    )
    key = resp.get("data", {}).get("collectSearchKey")
    if not key:
        raise RuntimeError(f"could not fetch collectSearchKey: {resp}")
    return key


def algolia_search(api_key: str, query: str | None, marketplace: str | None,
                   page: int, hits_per_page: int) -> dict:
    url = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
    body: dict = {"hitsPerPage": hits_per_page, "page": page}
    if query:
        body["query"] = query
    if marketplace:
        body["filters"] = f"marketplace:{marketplace}"
    return http_post_json(
        url, body,
        headers={"x-algolia-application-id": ALGOLIA_APP_ID,
                 "x-algolia-api-key": api_key},
    )


def parse_input_url(url: str) -> tuple[str | None, str | None]:
    """Extract (query, marketplace_type) from a fanaticscollect URL."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    return qs.get("q", [None])[0], qs.get("type", [None])[0]


SLUG_NONALNUM = re.compile(r"[^a-zA-Z0-9]+")


def safe_filename(s: str, ext: str = "") -> str:
    s = SLUG_NONALNUM.sub("_", s).strip("_").lower()
    return s[:120] + ext


def listing_url_for(hit: dict) -> str:
    """Best-effort canonical listing URL.

    The Algolia hit doesn't include the listing slug needed for a deep-link.
    Falling back to a marketplace search anchored on the listing title — for
    a unique title this lands on the same listing card.
    """
    mp = (hit.get("marketplace") or "").upper()
    title = hit.get("title") or str(hit.get("listingId"))
    qs = urllib.parse.quote(title)
    if mp in {"WEEKLY", "PREMIER", "FIXED"}:
        return f"https://www.fanaticscollect.com/marketplace?type={mp}&q={qs}"
    return f"https://www.fanaticscollect.com/marketplace?q={qs}"


def normalize(hit: dict) -> dict | None:
    images = hit.get("images") or {}
    primary = images.get("primary") or {}
    img_url = primary.get("large") or primary.get("medium")
    if not img_url:
        return None
    return {
        "listing_id": hit.get("listingId"),
        "title": hit.get("title"),
        "subtitle": hit.get("subtitle"),
        "year": hit.get("year"),
        "marketplace": hit.get("marketplace"),
        "category": hit.get("category"),
        "image_url": img_url,
        "listing_url": listing_url_for(hit),
        "lot": hit.get("lotNumber"),
        "auction_name": hit.get("auctionName"),
    }


def download_image(url: str, dest_dir: Path, basename: str) -> Path:
    data = http_get_bytes(url)
    # Sniff extension from content
    if data[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = ".webp"
    else:
        ext = ".bin"
    path = dest_dir / (basename + ext)
    path.write_bytes(data)
    return path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url", help="Fanatics Collect URL or raw search query")
    p.add_argument("--max", type=int, default=50, help="Max listings to fetch")
    p.add_argument("--per-page", type=int, default=50)
    p.add_argument("--download", type=Path, default=None,
                   help="Directory to download primary card images into")
    p.add_argument("--manifest", type=Path, default=None,
                   help="Write JSON manifest here (default: stdout)")
    args = p.parse_args(argv)

    if args.url.startswith(("http://", "https://")):
        query, marketplace = parse_input_url(args.url)
    else:
        # Treat as raw query string
        query, marketplace = args.url, None

    api_key = fetch_search_key()
    listings: list[dict] = []
    page = 0
    while len(listings) < args.max:
        per_page = min(args.per_page, args.max - len(listings))
        resp = algolia_search(api_key, query, marketplace, page, per_page)
        hits = resp.get("hits", [])
        if not hits:
            break
        for h in hits:
            n = normalize(h)
            if n:
                listings.append(n)
        if page + 1 >= resp.get("nbPages", 0):
            break
        page += 1

    if args.download:
        args.download.mkdir(parents=True, exist_ok=True)
        for entry in listings:
            base = safe_filename(f"{entry['listing_id']}_{entry['title'] or ''}")
            try:
                path = download_image(entry["image_url"], args.download, base)
                entry["image_path"] = str(path)
            except Exception as e:
                entry["image_error"] = str(e)

    out = json.dumps(listings, indent=2)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(out)
        print(f"wrote {len(listings)} listings to {args.manifest}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
