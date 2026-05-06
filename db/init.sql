PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS listings (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  title         TEXT NOT NULL,
  price         REAL,                      -- NULL = auction/offer only
  price_type    TEXT DEFAULT 'fixed',      -- 'fixed' | 'auction' | 'offer'
  image_url     TEXT,
  source_url    TEXT NOT NULL UNIQUE,
  condition     TEXT,                      -- 'new' | 'used' | 'not_specified'
  seller        TEXT,
  seller_rating REAL,
  category      TEXT,                      -- inferred: 'princess','villain','attraction',etc.
  tags          TEXT,                      -- JSON array
  is_active     INTEGER DEFAULT 1,
  is_curated    INTEGER DEFAULT 0,         -- 1 = Hermes reviewed + approved
  curator_notes TEXT,
  scraped_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

-- Full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS listings_fts USING fts5(
  title, category, tags,
  content=listings, content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS listings_ai AFTER INSERT ON listings BEGIN
  INSERT INTO listings_fts(rowid, title, category, tags)
  VALUES (new.id, new.title, new.category, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS listings_au AFTER UPDATE ON listings BEGIN
  INSERT INTO listings_fts(listings_fts, rowid, title, category, tags)
  VALUES ('delete', old.id, old.title, old.category, old.tags);
  INSERT INTO listings_fts(rowid, title, category, tags)
  VALUES (new.id, new.title, new.category, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS listings_ad AFTER DELETE ON listings BEGIN
  INSERT INTO listings_fts(listings_fts, rowid, title, category, tags)
  VALUES ('delete', old.id, old.title, old.category, old.tags);
END;

-- Scrape run log
CREATE TABLE IF NOT EXISTS scrape_runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  new_count   INTEGER DEFAULT 0,
  updated_count INTEGER DEFAULT 0,
  dropped_count INTEGER DEFAULT 0,
  error       TEXT
);
