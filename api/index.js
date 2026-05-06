import Fastify from 'fastify'
import Database from 'better-sqlite3'
import { fileURLToPath } from 'url'
import { join, dirname } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const DB_PATH = join(__dirname, '../db/pins.db')
const PORT = 3722

const db = new Database(DB_PATH, { readonly: true })
db.pragma('journal_mode = WAL')

const app = Fastify({ logger: false })

// GET /api/listings?q=&category=&tag=&source=&limit=&offset=&sort=&min_price=&max_price=
app.get('/api/listings', async (req, reply) => {
  const {
    q = '',
    category = '',
    tag = '',
    source = '',
    limit = 48,
    offset = 0,
    sort = 'scraped_at',
    min_price,
    max_price,
  } = req.query

  const lim = Math.min(Number(limit), 200)
  const off = Number(offset)

  const VALID_SORTS = {
    price: 'price',
    price_asc: 'price',
    price_per_pin: 'price_per_pin',
    price_per_pin_asc: 'price_per_pin',
    scraped_at: 'scraped_at',
    title: 'title',
  }
  const SORT_DIR = {
    price: 'ASC',
    price_asc: 'ASC',
    price_per_pin: 'ASC',
    price_per_pin_asc: 'ASC',
    scraped_at: 'DESC',
    title: 'ASC',
  }
  const sortCol = VALID_SORTS[sort] || 'scraped_at'
  const sortDir = SORT_DIR[sort] || 'DESC'

  const tagClause = tag ? `AND (l.tags LIKE ? OR l.tags LIKE ? OR l.tags LIKE ? OR l.tags LIKE ?)` : ''
  const tagParams = tag ? [`["${tag}"]`, `["${tag}",%`, `%,"${tag}",%`, `%,"${tag}"]`] : []
  const catClause = category ? 'AND l.category = ?' : ''
  const catParam = category ? [category] : []
  const srcClause = source ? 'AND l.source = ?' : ''
  const srcParam = source ? [source] : []

  const tagClauseNL = tag ? `AND (tags LIKE ? OR tags LIKE ? OR tags LIKE ? OR tags LIKE ?)` : ''
  const catClauseNL = category ? 'AND category = ?' : ''
  const srcClauseNL = source ? 'AND source = ?' : ''

  const priceMin = min_price != null ? Number(min_price) : null
  const priceMax = max_price != null ? Number(max_price) : null
  const priceMinClause = priceMin != null ? 'AND price >= ?' : ''
  const priceMaxClause = priceMax != null ? 'AND price <= ?' : ''
  const priceMinParam = priceMin != null ? [priceMin] : []
  const priceMaxParam = priceMax != null ? [priceMax] : []

  let rows, total

  if (q) {
    rows = db.prepare(`
      SELECT l.* FROM listings l
      JOIN listings_fts f ON l.id = f.rowid
      WHERE listings_fts MATCH ?
        AND l.is_active = 1
        ${catClause}
        ${tagClause}
        ${srcClause}
        ${priceMinClause}
        ${priceMaxClause}
      ORDER BY l.${sortCol} ${sortDir}
      LIMIT ? OFFSET ?
    `).all(...[`${q}*`, ...catParam, ...tagParams, ...srcParam, ...priceMinParam, ...priceMaxParam, lim, off])

    total = db.prepare(`
      SELECT COUNT(*) AS cnt FROM listings l
      JOIN listings_fts f ON l.id = f.rowid
      WHERE listings_fts MATCH ?
        AND l.is_active = 1
        ${catClause}
        ${tagClause}
        ${srcClause}
        ${priceMinClause}
        ${priceMaxClause}
    `).get(...[`${q}*`, ...catParam, ...tagParams, ...srcParam, ...priceMinParam, ...priceMaxParam]).cnt
  } else {
    rows = db.prepare(`
      SELECT * FROM listings
      WHERE is_active = 1
        ${catClauseNL}
        ${tagClauseNL}
        ${srcClauseNL}
        ${priceMinClause}
        ${priceMaxClause}
      ORDER BY ${sortCol} ${sortDir}
      LIMIT ? OFFSET ?
    `).all(...[...catParam, ...tagParams, ...srcParam, ...priceMinParam, ...priceMaxParam, lim, off])

    total = db.prepare(`
      SELECT COUNT(*) AS cnt FROM listings
      WHERE is_active = 1
        ${catClauseNL}
        ${tagClauseNL}
        ${srcClauseNL}
        ${priceMinClause}
        ${priceMaxClause}
    `).get(...[...catParam, ...tagParams, ...srcParam, ...priceMinParam, ...priceMaxParam]).cnt
  }

  const listings = rows.map(r => ({
    ...r,
    tags: (() => { try { return JSON.parse(r.tags) } catch { return [] } })()
  }))

  return { listings, total, limit: lim, offset: off }
})

// GET /api/sources
app.get('/api/sources', async () => {
  const rows = db.prepare(`
    SELECT source, COUNT(*) AS count
    FROM listings WHERE is_active = 1
    GROUP BY source ORDER BY count DESC
  `).all()
  return { sources: rows }
})

// GET /api/categories
app.get('/api/categories', async () => {
  const rows = db.prepare(`
    SELECT category, COUNT(*) AS count
    FROM listings WHERE is_active = 1
    GROUP BY category ORDER BY count DESC
  `).all()
  return { categories: rows }
})

// GET /api/stats
app.get('/api/stats', async () => {
  const total = db.prepare("SELECT COUNT(*) AS n FROM listings WHERE is_active=1").get().n
  const lastRun = db.prepare("SELECT finished_at, new_count, updated_count FROM scrape_runs ORDER BY id DESC LIMIT 1").get()
  const bestValue = db.prepare(`
    SELECT title, price, quantity, price_per_pin, image_url, source_url
    FROM listings
    WHERE is_active=1 AND price_per_pin IS NOT NULL AND quantity >= 10
    ORDER BY price_per_pin ASC LIMIT 3
  `).all()
  return { total_listings: total, last_scrape: lastRun || null, best_value: bestValue }
})

// Health
app.get('/api/health', async () => ({ ok: true }))

app.listen({ port: PORT, host: '127.0.0.1' }, (err) => {
  if (err) { console.error(err); process.exit(1) }
  console.log(`PinTrader API listening on :${PORT}`)
})
