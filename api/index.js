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

// GET /api/listings?q=&category=&tag=&limit=&offset=&sort=
app.get('/api/listings', async (req, reply) => {
  const {
    q = '',
    category = '',
    tag = '',
    limit = 48,
    offset = 0,
    sort = 'scraped_at',
  } = req.query

  const lim = Math.min(Number(limit), 200)
  const off = Number(offset)
  const validSort = ['price', 'scraped_at', 'title'].includes(sort) ? sort : 'scraped_at'

  // tag filter: JSON array contains the tag value
  const tagClause = tag ? `AND (l.tags LIKE ? OR l.tags LIKE ? OR l.tags LIKE ? OR l.tags LIKE ?)` : ''
  const tagParams = tag ? [`["${tag}"]`, `["${tag}",%`, `%,"${tag}",%`, `%,"${tag}"]`] : []

  const catClause = category ? 'AND l.category = ?' : ''
  const catParam = category ? [category] : []

  // Non-FTS equivalents (no l. prefix)
  const tagClauseNL = tag ? `AND (tags LIKE ? OR tags LIKE ? OR tags LIKE ? OR tags LIKE ?)` : ''
  const catClauseNL = category ? 'AND category = ?' : ''

  let rows, total

  if (q) {
    // FTS search
    rows = db.prepare(`
      SELECT l.* FROM listings l
      JOIN listings_fts f ON l.id = f.rowid
      WHERE listings_fts MATCH ?
        AND l.is_active = 1
        ${catClause}
        ${tagClause}
      ORDER BY l.${validSort} DESC
      LIMIT ? OFFSET ?
    `).all(...[`${q}*`, ...catParam, ...tagParams, lim, off])

    total = db.prepare(`
      SELECT COUNT(*) AS cnt FROM listings l
      JOIN listings_fts f ON l.id = f.rowid
      WHERE listings_fts MATCH ?
        AND l.is_active = 1
        ${catClause}
        ${tagClause}
    `).get(...[`${q}*`, ...catParam, ...tagParams]).cnt
  } else {
    rows = db.prepare(`
      SELECT * FROM listings
      WHERE is_active = 1
        ${catClauseNL}
        ${tagClauseNL}
      ORDER BY ${validSort} DESC
      LIMIT ? OFFSET ?
    `).all(...[...catParam, ...tagParams, lim, off])

    total = db.prepare(`
      SELECT COUNT(*) AS cnt FROM listings
      WHERE is_active = 1
        ${catClauseNL}
        ${tagClauseNL}
    `).get(...[...catParam, ...tagParams]).cnt
  }

  // Parse tags JSON
  const listings = rows.map(r => ({
    ...r,
    tags: (() => { try { return JSON.parse(r.tags) } catch { return [] } })()
  }))

  return { listings, total, limit: lim, offset: off }
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
  return { total_listings: total, last_scrape: lastRun || null }
})

// Health
app.get('/api/health', async () => ({ ok: true }))

app.listen({ port: PORT, host: '127.0.0.1' }, (err) => {
  if (err) { console.error(err); process.exit(1) }
  console.log(`PinTrader API listening on :${PORT}`)
})
