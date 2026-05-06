#!/usr/bin/env python3
"""
Migration: add `source` column to listings and backfill existing rows as 'ebay'.
Safe to run multiple times (checks if column exists first).
"""
import sqlite3, sys

DB_PATH = "/opt/pintrader/db/pins.db"

con = sqlite3.connect(DB_PATH)
cols = [r[1] for r in con.execute("PRAGMA table_info(listings)").fetchall()]

if "source" in cols:
    print("Column 'source' already exists — nothing to do.")
    con.close()
    sys.exit(0)

con.execute("ALTER TABLE listings ADD COLUMN source TEXT DEFAULT 'ebay'")
con.execute("UPDATE listings SET source = 'ebay' WHERE source IS NULL")
con.commit()
count = con.execute("SELECT COUNT(*) FROM listings WHERE source = 'ebay'").fetchone()[0]
print(f"Done. Backfilled {count} rows with source='ebay'.")
con.close()
