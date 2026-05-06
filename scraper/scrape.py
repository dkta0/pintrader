#!/usr/bin/env python3
"""
Disney pin scraper — eBay + Mercari
Uses crawl4ai container on :11235
Inserts/updates listings in /opt/pintrader/db/pins.db
"""

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode, quote_plus
from urllib.request import urlopen, Request
from urllib.error import URLError

DB_PATH = "/opt/pintrader/db/pins.db"
CRAWL4AI_URL = "http://localhost:11235"

# Shared search terms — used across all sources
SEARCH_TERMS = [
    # Bulk/lot
    "disney pin trading lot",
    "disney limited edition pin",
    # Attractions
    "disney haunted mansion pin",
    "disney pirates of the caribbean pin",
    "disney space mountain pin",
    "disney jungle cruise pin",
    # Characters
    "disney villain pin maleficent ursula",
    "disney princess pin ariel cinderella",
    "disney mickey mouse pin",
    "disney star wars galaxy edge pin",
    "disney marvel pin",
    "disney pixar pin",
    # Series/event
    "disney EPCOT world showcase pin",
    "disney D23 exclusive pin",
    "disney artist series pin",
    "disney mystery pin",
    # Park exclusives
    "disney park exclusive pin 2025",
    "disney park exclusive pin 2026",
]

CATEGORY_RULES = [
    (r'\b(cinderella|belle|ariel|rapunzel|moana|tiana|snow white|aurora|pocahontas|merida|raya|princess|jasmine|mulan|elena|mirabel|encanto)\b', 'princess'),
    (r'\b(maleficent|ursula|gaston|jafar|cruella|villain|evil queen|scar|hades|yzma|dr facilier|mother gothel)\b', 'villain'),
    (r'\b(haunted mansion|pirates|caribbean|space mountain|big thunder|matterhorn|splash mountain|tomorrowland|fantasyland|attraction|ride|jungle cruise|tower of terror|horizons|soarin|its a small world|small world|dumbo|peter pan|buzz lightyear|winnie the pooh)\b', 'attraction'),
    (r'\b(castle|cinderella castle|sleeping beauty castle|magic kingdom)\b', 'castle'),
    (r'\b(mickey|minnie|donald|goofy|pluto|chip|dale|daisy|oswald|tinker bell|peter pan|dumbo|bambi|stitch|lilo)\b', 'classic'),
    (r"\\b(star wars|darth|lightsaber|galaxy'?s edge|mandalorian|grogu|baby yoda|r2d2|bb-?8|obi.wan|luke|leia|vader|boba fett)\\b", 'star-wars'),
    (r'\b(marvel|avengers|spider.?man|iron man|captain america|thor|black widow|hulk|black panther|guardians)\b', 'marvel'),
    (r'\b(pixar|woody|buzz|nemo|dory|wall.?e|up|coco|incredibles|ratatouille|monsters inc|boo|sully|cars|lightning mcqueen)\b', 'pixar'),
    (r'\b(holiday|christmas|halloween|easter|hanukkah|seasonal|nightmare before christmas|jack skellington|santa)\b', 'holiday'),
    (r'\b(epcot|world showcase|france|germany|japan|canada|uk pavilion|mexico|norway|china|morocco|italy|american|world of color)\b', 'epcot'),
    (r'\b(limited edition|le \d+|htf|hard to find|rare|grail|d23|artist series|mystery)\b', 'limited'),
]

BULK_LOT_PATTERNS = [
    (r'\b(villain|maleficent|ursula|evil queen|scar|hades|cruella)\b', 'villain'),
    (r'\b(princess|ariel|belle|cinderella|rapunzel|moana|aurora|tiana)\b', 'princess'),
    (r'\b(haunted mansion|pirates|space mountain|jungle cruise|attraction)\b', 'attraction'),
    (r'\b(mickey|minnie|classic|character)\b', 'classic'),
    (r'\b(star wars|galaxy)\b', 'star-wars'),
    (r'\b(marvel|avengers)\b', 'marvel'),
    (r'\b(pixar)\b', 'pixar'),
    (r'\b(holiday|halloween|christmas)\b', 'holiday'),
    (r'\b(epcot|world showcase)\b', 'epcot'),
    (r'\b(castle)\b', 'castle'),
    (r'\b(limited|le \d+|htf|mystery|d23)\b', 'limited'),
]

QTY_PATTERNS = [
    r'lot\s+of\s+(\d+)',
    r'(\d+)\s*(?:disney\s+)?(?:trading\s+)?pins?\s+lot',
    r'pick\s+size\s+(?:from\s+)?(?:\d+[-–]\s*)?(\d+)',
    r'(?:pack|set|bundle|assorted)\s+of\s+(\d+)',
    r'\b(\d+)\s+(?:disney\s+)?(?:trading\s+)?pins?\b',
    r'\b(\d+)\s+(?:assorted|authentic|different|unique|tradable)',
    r'\b(\d{2,})\s+(?:lot|pins)',
]


def parse_quantity(title: str):
    t = title.lower()
    for pat in QTY_PATTERNS:
        m = re.search(pat, t)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 2000:
                return val
    return None


def is_bulk_lot(title: str) -> bool:
    t = title.lower()
    return bool(re.search(r'\b(lot|bulk|assorted|pick size|no doubles|no duplicates|tradable pins)\b', t))


def infer_category(title: str) -> str:
    t = title.lower()
    if is_bulk_lot(t):
        for pattern, cat in BULK_LOT_PATTERNS:
            if re.search(pattern, t):
                return cat
        return 'other'
    for pattern, cat in CATEGORY_RULES:
        if re.search(pattern, t):
            return cat
    return 'other'


def infer_tags(title: str) -> list:
    t = title.lower()
    tags = set()
    for pattern, cat in CATEGORY_RULES:
        if re.search(pattern, t):
            tags.add(cat)
    if re.search(r'\b(le |limited edition)\b', t):
        tags.add('limited')
    if re.search(r'\b(htf|hard to find|grail|rare)\b', t):
        tags.add('htf')
    if re.search(r'\bfree\s+shipping\b', t):
        tags.add('free-shipping')
    if re.search(r'\b(park exclusive|exclusive|park only)\b', t):
        tags.add('park-exclusive')
    if re.search(r'\b(d23)\b', t):
        tags.add('d23')
    if re.search(r'\b(mystery)\b', t):
        tags.add('mystery')
    return list(tags)


def crawl(url: str) -> dict:
    payload = json.dumps({
        "urls": [url],
        "headless": True,
        "page_timeout": 30000,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        },
    }).encode()
    req = Request(
        f"{CRAWL4AI_URL}/crawl",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    if isinstance(data.get("results"), list) and data["results"]:
        return {"success": data.get("success", True), "html": data["results"][0].get("html", "")}
    return {"success": False, "html": ""}


def parse_price(price_str: str):
    if not price_str:
        return None, 'fixed'
    s = price_str.strip()
    nums = re.findall(r'[\d,]+\.?\d*', s)
    if nums:
        return float(nums[0].replace(',', '')), 'fixed'
    return None, 'offer'


# ── eBay ──────────────────────────────────────────────────────────────────────

def scrape_ebay(query: str) -> list:
    params = urlencode({"_nkw": query, "_sacat": "0", "LH_BIN": "1"})
    url = f"https://www.ebay.com/sch/i.html?{params}"
    print(f"  [ebay] {query}", flush=True)

    try:
        result = crawl(url)
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        return []

    if not result.get("success") or not result.get("html"):
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(result["html"], "html.parser")
    items = soup.select("li[data-listingid]")
    print(f"  → {len(items)} raw items", flush=True)

    listings = []
    for item in items:
        img = item.select_one("img[alt]")
        title = (img.get("alt") or "").strip() if img else ""
        if not title or title.lower() in ("shop on ebay",):
            continue
        if not re.search(r'disney|pin', title, re.I):
            continue

        links = [a for a in item.select("a[href]") if "/itm/" in a.get("href", "")]
        if not links:
            continue
        href = links[0].get("href", "")
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.ebay.com" + href
        source_url = href.split("?")[0]

        image_url = (img.get("src") or img.get("data-src")) if img else None
        if image_url and "ebaystatic" in (image_url or ""):
            image_url = None

        price_str = next((t.strip() for t in item.find_all(string=re.compile(r'\$\d'))), "")
        price, price_type = parse_price(price_str)
        if price and price > 500:
            continue

        cond_el = item.select_one(".SECONDARY_INFO") or item.select_one("[class*='condition']")
        condition_raw = cond_el.get_text(strip=True).lower() if cond_el else ""
        condition = "new" if "new" in condition_raw else "used" if "used" in condition_raw else "not_specified"

        seller_el = item.select_one("[class*='seller']")
        seller = seller_el.get_text(strip=True) if seller_el else None

        category = infer_category(title)
        tags = infer_tags(title)
        quantity = parse_quantity(title)
        price_per_pin = round(price / quantity, 4) if quantity and price else None

        listings.append({
            "source": "ebay",
            "title": title,
            "price": price,
            "price_type": price_type,
            "image_url": image_url,
            "source_url": source_url,
            "condition": condition,
            "seller": seller,
            "seller_rating": None,
            "category": category,
            "tags": json.dumps(tags),
            "quantity": quantity,
            "price_per_pin": price_per_pin,
            "is_active": 1,
            "is_curated": 0,
        })

    return listings


# ── Mercari ───────────────────────────────────────────────────────────────────

def scrape_mercari(query: str) -> list:
    url = f"https://www.mercari.com/search/?keyword={quote_plus(query)}&status=on_sale"
    print(f"  [mercari] {query}", flush=True)

    try:
        result = crawl(url)
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        return []

    if not result.get("success") or not result.get("html"):
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(result["html"], "html.parser")

    # Mercari renders item cards as <li> or <div> with data-testid or class patterns
    # Try multiple selectors — Mercari's DOM changes occasionally
    items = (
        soup.select("li[data-testid='item-cell']") or
        soup.select("div[data-testid='item-cell']") or
        soup.select("[class*='SearchResults'] li") or
        soup.select("[class*='items-box'] li") or
        []
    )
    print(f"  → {len(items)} raw items", flush=True)

    listings = []
    for item in items:
        # Title: from aria-label, alt text, or heading
        title = ""
        title_el = (
            item.select_one("[data-testid='item-name']") or
            item.select_one("h3") or
            item.select_one("[class*='itemName']") or
            item.select_one("[class*='item-name']")
        )
        if title_el:
            title = title_el.get_text(strip=True)
        if not title:
            img = item.select_one("img[alt]")
            title = img.get("alt", "").strip() if img else ""
        if not title:
            continue
        if not re.search(r'disney|pin', title, re.I):
            continue

        # Link
        link_el = item.select_one("a[href*='/item/']") or item.select_one("a[href]")
        if not link_el:
            continue
        href = link_el.get("href", "")
        if href.startswith("/"):
            href = "https://www.mercari.com" + href
        source_url = href.split("?")[0]
        if not source_url or "mercari.com" not in source_url:
            continue

        # Image
        img = item.select_one("img")
        image_url = None
        if img:
            image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if image_url and ("placeholder" in image_url or "static" in image_url or len(image_url) < 20):
                image_url = None

        # Price
        price_el = (
            item.select_one("[data-testid='item-price']") or
            item.select_one("[class*='price']") or
            item.select_one("span[aria-label*='$']")
        )
        price_str = price_el.get_text(strip=True) if price_el else ""
        # Also search for $ strings in item text
        if not price_str:
            price_str = next((t.strip() for t in item.find_all(string=re.compile(r'\$\d'))), "")
        price, price_type = parse_price(price_str)
        if price and price > 500:
            continue
        if not price:
            continue  # skip items without a visible price

        # Condition — Mercari shows "Like New", "Good", "Fair", etc.
        cond_el = item.select_one("[class*='condition']") or item.select_one("[data-testid='item-condition']")
        condition_raw = cond_el.get_text(strip=True).lower() if cond_el else ""
        if "new" in condition_raw:
            condition = "new"
        elif any(x in condition_raw for x in ("good", "fair", "poor", "used", "like")):
            condition = "used"
        else:
            condition = "not_specified"

        # Seller
        seller_el = item.select_one("[class*='seller']") or item.select_one("[data-testid*='seller']")
        seller = seller_el.get_text(strip=True) if seller_el else None

        category = infer_category(title)
        tags = infer_tags(title)
        quantity = parse_quantity(title)
        price_per_pin = round(price / quantity, 4) if quantity and price else None

        listings.append({
            "source": "mercari",
            "title": title,
            "price": price,
            "price_type": price_type,
            "image_url": image_url,
            "source_url": source_url,
            "condition": condition,
            "seller": seller,
            "seller_rating": None,
            "category": category,
            "tags": json.dumps(tags),
            "quantity": quantity,
            "price_per_pin": price_per_pin,
            "is_active": 1,
            "is_curated": 0,
        })

    return listings


# ── DB upsert ─────────────────────────────────────────────────────────────────

def upsert(con: sqlite3.Connection, listing: dict, now: str) -> str:
    existing = con.execute(
        "SELECT id, price, is_active FROM listings WHERE source_url = ?",
        (listing["source_url"],)
    ).fetchone()

    if existing:
        if existing[1] != listing["price"] or existing[2] != 1:
            con.execute("""
                UPDATE listings SET price=?, is_active=1, updated_at=?,
                  quantity=?, price_per_pin=?, category=?, tags=?, source=?
                WHERE id=?
            """, (listing["price"], now, listing["quantity"], listing["price_per_pin"],
                  listing["category"], listing["tags"], listing["source"], existing[0]))
            return "updated"
        return "skip"
    else:
        con.execute("""
            INSERT INTO listings
              (title, price, price_type, image_url, source_url, condition,
               seller, seller_rating, category, tags, quantity, price_per_pin,
               source, is_active, is_curated, scraped_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            listing["title"], listing["price"], listing["price_type"],
            listing["image_url"], listing["source_url"], listing["condition"],
            listing["seller"], listing["seller_rating"], listing["category"],
            listing["tags"], listing["quantity"], listing["price_per_pin"],
            listing["source"], 1, 0, now, now
        ))
        return "new"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(DB_PATH)

    run_id = con.execute(
        "INSERT INTO scrape_runs (started_at) VALUES (?)", (now,)
    ).lastrowid
    con.commit()

    new_count = updated_count = dropped_count = 0
    error = None

    SCRAPERS = [
        ("ebay", scrape_ebay),
        ("mercari", scrape_mercari),
    ]

    try:
        for source_name, scrape_fn in SCRAPERS:
            print(f"\n=== {source_name.upper()} ===", flush=True)
            for query in SEARCH_TERMS:
                listings = scrape_fn(query)
                print(f"  → {len(listings)} listings parsed", flush=True)
                for l in listings:
                    result = upsert(con, l, now)
                    if result == "new":
                        new_count += 1
                    elif result == "updated":
                        updated_count += 1
                con.commit()

        # Mark stale listings inactive (not seen in 14 days)
        con.execute("""
            UPDATE listings SET is_active=0, updated_at=?
            WHERE is_active=1
              AND updated_at < datetime('now', '-14 days')
        """, (now,))
        dropped_count = con.execute("SELECT changes()").fetchone()[0]
        con.commit()

    except Exception as e:
        error = str(e)
        print(f"FATAL: {e}", flush=True)

    finished = datetime.now(timezone.utc).isoformat()
    con.execute("""
        UPDATE scrape_runs SET finished_at=?, new_count=?, updated_count=?, dropped_count=?, error=?
        WHERE id=?
    """, (finished, new_count, updated_count, dropped_count, error, run_id))
    con.commit()
    con.close()

    print(f"\nDone. new={new_count} updated={updated_count} stale_dropped={dropped_count}")
    if error:
        print(f"Error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
