"""
store.py - the database. Everything the pipeline remembers lives here.

We use SQLite: a whole database in one file (data/sitaware.db). No server to install,
built into Python, and you can query it with plain SQL. Three tables:

  articles     one row per article we've ever seen (kept for KEEP_DAYS days)
  feed_state   per feed: ETag/Last-Modified for conditional requests, and failure streaks
  fetch_log    one row per feed per run: what happened (for health reports)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from config import ROOT

DB_PATH = ROOT / "data" / "sitaware.db"
KEEP_DAYS = 30          # older articles are deleted at the end of each run
DUPE_TITLE_DAYS = 3     # same headline within 3 days on the same site = duplicate

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            TEXT PRIMARY KEY,   -- hash of site + canonical URL: makes re-inserts impossible
    site          TEXT NOT NULL,      -- geo | cyber
    source        TEXT NOT NULL,      -- name from sources.yaml
    outlet        TEXT,               -- real publisher (differs for Google News feeds)
    url           TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title         TEXT NOT NULL,
    title_key     TEXT NOT NULL,
    summary       TEXT,
    published     TEXT NOT NULL,      -- ISO dates sort correctly as text
    first_seen    TEXT NOT NULL,
    region        TEXT,
    section       TEXT,
    topics        TEXT,
    lang          TEXT,
    type          TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_site_published ON articles(site, published);
CREATE INDEX IF NOT EXISTS idx_articles_title_key ON articles(site, title_key);

CREATE TABLE IF NOT EXISTS feed_state (
    feed          TEXT PRIMARY KEY,
    etag          TEXT,
    modified      TEXT,
    last_ok       TEXT,
    last_error    TEXT,
    fails_in_row  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fetch_log (
    run_at   TEXT, site TEXT, source TEXT, status TEXT,
    items    INTEGER, new INTEGER, dupes INTEGER, old INTEGER, error TEXT
);
"""


def connect() -> sqlite3.Connection:
    """Open (or create) the database file and make sure the tables exist."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # rows behave like dicts: row["title"]
    conn.executescript(SCHEMA)
    return conn


def feed_states(conn) -> dict[str, dict]:
    return {r["feed"]: dict(r) for r in conn.execute("SELECT * FROM feed_state")}


def save_feed_state(conn, feed: str, ok: bool, now: str, etag=None, modified=None, error=None):
    if ok:
        conn.execute(
            """INSERT INTO feed_state(feed, etag, modified, last_ok, last_error, fails_in_row)
               VALUES (?, ?, ?, ?, NULL, 0)
               ON CONFLICT(feed) DO UPDATE SET etag=excluded.etag, modified=excluded.modified,
                   last_ok=excluded.last_ok, last_error=NULL, fails_in_row=0""",
            (feed, etag, modified, now),
        )
    else:
        conn.execute(
            """INSERT INTO feed_state(feed, last_error, fails_in_row) VALUES (?, ?, 1)
               ON CONFLICT(feed) DO UPDATE SET last_error=excluded.last_error,
                   fails_in_row=feed_state.fails_in_row + 1""",
            (feed, error),
        )


def is_title_dupe(conn, art: dict) -> bool:
    """Same site, same headline fingerprint, within DUPE_TITLE_DAYS? Then it's the same story re-posted."""
    if len(art["title_key"]) < 25:      # short titles ("Live updates") collide by accident
        return False
    since = (datetime.fromisoformat(art["published"]) - timedelta(days=DUPE_TITLE_DAYS)).isoformat()
    row = conn.execute(
        "SELECT 1 FROM articles WHERE site=? AND title_key=? AND published>=? LIMIT 1",
        (art["site"], art["title_key"], since),
    ).fetchone()
    return row is not None


def insert_article(conn, art: dict) -> str:
    """Insert one article. Returns 'new', 'seen' (same URL already stored) or 'dupe' (same headline)."""
    if conn.execute("SELECT 1 FROM articles WHERE id=?", (art["id"],)).fetchone():
        return "seen"
    if is_title_dupe(conn, art):
        return "dupe"
    cols = ",".join(art)
    conn.execute(f"INSERT INTO articles({cols}) VALUES ({','.join('?' * len(art))})", tuple(art.values()))
    return "new"


def log_fetch(conn, **row):
    conn.execute(
        "INSERT INTO fetch_log(run_at, site, source, status, items, new, dupes, old, error) VALUES (?,?,?,?,?,?,?,?,?)",
        (row["run_at"], row["site"], row["source"], row["status"], row.get("items", 0),
         row.get("new", 0), row.get("dupes", 0), row.get("old", 0), row.get("error")),
    )


def prune(conn) -> int:
    """Delete articles and logs older than KEEP_DAYS so the database stays small."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    n = conn.execute("DELETE FROM articles WHERE published < ?", (cutoff,)).rowcount
    conn.execute("DELETE FROM fetch_log WHERE run_at < ?", (cutoff,))
    return n
