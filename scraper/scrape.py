#!/usr/bin/env python3
"""
eBay Disney pin scraper using crawl4ai container on :11235
Inserts/updates listings in /opt/pintrader/db/pins.db
"""

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError

DB_PATH = "/opt/pintrader/db/pins.db"
CRAWL4AI_URL = "http://localhost:11235"

# eBay search URLs — multiple queries for broader coverage
EBAY_SEARCHES = [
    "disney pin trading",
    "disney limited edition pin",
    "disney park pin",
    "disney villain pin",
    "disney princess pin",
    "disney attraction pin",
]

CATEGORY_RULES = [
    (r'\b(cinderella|belle|ariel|rapunzel|moana|tiana|snow white|aurora|pocahontas|merida|raya|princess)\b', 'princess'),
    (r'\b(maleficent|ursula|gaston|jafar|cruella|villain|evil queen|scar)\b', 'villain'),
    (r'\b(haunted mansion|pirates|space mountain|big thunder|matterhorn|splash mountain|tomorrowland|fantasyland|attraction|ride)\b', 'attraction'),
    (r'\b(castle|cinderella castle|sleeping beauty castle|magic kingdom)\b', 'castle'),
    (r'\b(mickey|minnie|donald|goofy|pluto|chip|dale|daisy)\b', 'classic'),
    (r'\b(star wars|darth|lightsaber|galaxy\'s edge|mandalorian)\b', 'star-wars'),
    (r'\b(marvel|avengers|spider.?man|iron man|captain america)\b', 'marvel'),
    (r'\b(pixar|woody|buzz|nemo|wall.?e|up|coco|incredibles)\b', 'pixar'),
    (r'\b(holiday|christmas|halloween|easter|hanukkah|seasonal)\b', 'holiday'),
    (r'\b(epcot|world showcase|france|germany|japan|canada|uk pavilion)\b', 'epcot'),
    (r'\b(limited edition|le \d+|htf|hard to find|rare|grail)\b', 'limited'),
]

def infer_category(title: str) -> str:
    t = title.lower()
    for pattern, cat in CATEGORY_RULES:
        if re.search(pattern, t):
            return cat
    return 'other'

def infer_tags(title: str) -> list:
    t = title.lower()
    tags = []
    for pattern, cat in CATEGORY_RULES:
        if re.search(pattern, t):
            tags.append(cat)
    if re.search(r'\b(le |limited edition)\b', t):
        tags.append('limited')
    if re.search(r'\b(htf|hard to find|grail|rare)\b', t):
        tags.append('htf')
    return list(set(tags))

def crawl(url: str) -> dict:
    """Fetch eBay search page HTML via crawl4ai and return the result dict."""
    payload = json.dumps({
        "urls": [url],          # must be a list in crawl4ai v0.8+
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
    # v0.8 wraps results in a list
    if isinstance(data.get("results"), list) and data["results"]:
        return {"success": data.get("success", True), "html": data["results"][0].get("html", "")}
    return {"success": False, "html": ""}

def parse_price(price_str: str):
    if not price_str:
        return None, 'fixed'
    s = price_str.strip()
    if 'to' in s.lower() or ' - ' in s:
        # range — take lower
        parts = re.findall(r'[\d,]+\.?\d*', s)
        if parts:
            return float(parts[0].replace(',', '')), 'fixed'
    nums = re.findall(r'[\d,]+\.?\d*', s)
    if nums:
        return float(nums[0].replace(',', '')), 'fixed'
    return None, 'offer'

def scrape_ebay(query: str) -> list:
    params = urlencode({
        "_nkw": query,
        "_sacat": "0",
        "LH_BIN": "1",  # Buy It Now only
    })
    url = f"https://www.ebay.com/sch/i.html?{params}"
    print(f"  Scraping: {query}", flush=True)

    try:
        result = crawl(url)
    except Exception as e:
        print(f"  ERROR crawling {query}: {e}", flush=True)
        return []

    if not result.get("success") or not result.get("html"):
        print(f"  Crawl failed or empty HTML", flush=True)
        return []

    from bs4 import BeautifulSoup
    import re as _re
    soup = BeautifulSoup(result["html"], "html.parser")
    items = soup.select("li[data-listingid]")
    print(f"  → {len(items)} raw items in HTML", flush=True)

    listings = []
    for item in items:
        # Title from image alt (most reliable)
        img = item.select_one("img[alt]")
        title = (img.get("alt") or "").strip() if img else ""
        if not title or title.lower() in ("shop on ebay",):
            continue
        if not _re.search(r'disney|pin', title, _re.I):
            continue

        # Link — prefer /itm/ URLs
        links = [a for a in item.select("a[href]") if "/itm/" in a.get("href", "")]
        if not links:
            continue
        href = links[0].get("href", "")
        # normalize — sometimes href is //www.ebay.com/itm/... or https://...
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.ebay.com" + href
        source_url = href.split("?")[0]

        # Image src
        image_url = (img.get("src") or img.get("data-src")) if img else None
        if image_url and "ebaystatic" in (image_url or ""):
            image_url = None  # placeholder image, not useful

        # Price — first $X.XX string in item text
        price_str = next((t.strip() for t in item.find_all(string=_re.compile(r'\$\d')) ), "")
        price, price_type = parse_price(price_str)
        if price and price > 500:
            continue

        # Condition
        cond_el = item.select_one(".SECONDARY_INFO") or item.select_one("[class*='condition']")
        condition_raw = cond_el.get_text(strip=True).lower() if cond_el else ""
        condition = "new" if "new" in condition_raw else "used" if "used" in condition_raw else "not_specified"

        # Seller
        seller_el = item.select_one("[class*='seller']")
        seller = seller_el.get_text(strip=True) if seller_el else None

        category = infer_category(title)
        tags = infer_tags(title)

        listings.append({
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
            "is_active": 1,
            "is_curated": 0,
        })

    return listings

def upsert(con: sqlite3.Connection, listing: dict, now: str) -> str:
    """Insert or update. Returns 'new', 'updated', or 'skip'."""
    existing = con.execute(
        "SELECT id, price, is_active FROM listings WHERE source_url = ?",
        (listing["source_url"],)
    ).fetchone()

    if existing:
        # Update price + active status if changed
        if existing[1] != listing["price"] or existing[2] != 1:
            con.execute("""
                UPDATE listings SET price=?, is_active=1, updated_at=? WHERE id=?
            """, (listing["price"], now, existing[0]))
            return "updated"
        return "skip"
    else:
        con.execute("""
            INSERT INTO listings
              (title, price, price_type, image_url, source_url, condition,
               seller, seller_rating, category, tags, is_active, is_curated,
               scraped_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            listing["title"], listing["price"], listing["price_type"],
            listing["image_url"], listing["source_url"], listing["condition"],
            listing["seller"], listing["seller_rating"], listing["category"],
            listing["tags"], 1, 0, now, now
        ))
        return "new"

def main():
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(DB_PATH)

    run_id = con.execute(
        "INSERT INTO scrape_runs (started_at) VALUES (?)", (now,)
    ).lastrowid
    con.commit()

    new_count = updated_count = dropped_count = 0
    error = None

    try:
        for query in EBAY_SEARCHES:
            listings = scrape_ebay(query)
            print(f"  → {len(listings)} listings parsed", flush=True)
            for l in listings:
                result = upsert(con, l, now)
                if result == "new":
                    new_count += 1
                elif result == "updated":
                    updated_count += 1
            con.commit()

        # Mark stale — listings not seen in this run that are > 14 days old
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
