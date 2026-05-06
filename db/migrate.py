#!/usr/bin/env python3
"""
Run once: add quantity and price_per_pin columns, then backfill from existing titles.
"""
import re
import sqlite3

DB_PATH = "/opt/pintrader/db/pins.db"

QTY_PATTERNS = [
    r'lot\s+of\s+(\d+)',
    r'(\d+)\s*(?:disney\s+)?(?:trading\s+)?pins?\s+lot',
    r'pick\s+size\s+(?:from\s+)?(?:\d+[-–]\s*)?(\d+)',
    r'(?:pack|set|bundle|assorted)\s+of\s+(\d+)',
    r'\b(\d+)\s+(?:disney\s+)?(?:trading\s+)?pins?\b',
    r'\b(\d+)\s+(?:assorted|authentic|different|unique|tradable)',
]

def parse_quantity(title: str) -> int | None:
    t = title.lower()
    for pat in QTY_PATTERNS:
        m = re.search(pat, t)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 2000:
                return val
    return None

def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Add columns if they don't exist
    cols = {r[1] for r in cur.execute("PRAGMA table_info(listings)")}
    if 'quantity' not in cols:
        cur.execute("ALTER TABLE listings ADD COLUMN quantity INTEGER")
        print("Added column: quantity")
    if 'price_per_pin' not in cols:
        cur.execute("ALTER TABLE listings ADD COLUMN price_per_pin REAL")
        print("Added column: price_per_pin")
    con.commit()

    # Backfill
    rows = cur.execute("SELECT id, title, price FROM listings").fetchall()
    updated = 0
    for row_id, title, price in rows:
        qty = parse_quantity(title)
        ppp = round(price / qty, 4) if qty and price else None
        if qty or ppp:
            cur.execute(
                "UPDATE listings SET quantity=?, price_per_pin=? WHERE id=?",
                (qty, ppp, row_id)
            )
            updated += 1
    con.commit()
    con.close()
    print(f"Backfilled {updated}/{len(rows)} rows")

if __name__ == "__main__":
    main()
