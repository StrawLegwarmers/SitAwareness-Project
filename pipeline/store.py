"""
store.py - the database. Everything the pipeline remembers lives here.

We use SQLite: a whole database in one file (data/sitaware.db). No server to install,
built into Python, and you can query it with plain SQL. Three tables:

  articles     one row per article we've ever seen (kept for KEEP_DAYS days)
  forgotten    ids of articles deleted by prune(), kept REMEMBER_DAYS (see insert_article)
  feed_state   per feed: ETag/Last-Modified for conditional requests, and failure streaks
  fetch_log    one row per feed per run: what happened (for health reports)
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import ROOT

# SITAWARE_DB=/tmp/test.db points everything at another database (the tests use this).
DB_PATH = Path(os.environ.get("SITAWARE_DB") or ROOT / "data" / "sitaware.db")
KEEP_DAYS = 30          # older articles are deleted at the end of each run
REMEMBER_DAYS = 120     # ...but their ids are remembered this long, so they never come back as "new"
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
    type          TEXT,
    kind          TEXT DEFAULT 'news' -- news | opinion | analysis (see content.py)
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

-- CISA's catalog of vulnerabilities known to be exploited (refreshed every run)
CREATE TABLE IF NOT EXISTS kev (
    cve TEXT PRIMARY KEY, vendor TEXT, product TEXT, name TEXT, description TEXT,
    date_added TEXT, due_date TEXT, ransomware TEXT
);

-- Indicators of compromise. 'value' is always stored DEFANGED (example[.]com).
CREATE TABLE IF NOT EXISTS iocs (
    source      TEXT,   -- outlet of the research report, or the tracker's name
    report_url  TEXT,   -- the report it came from ('' for trackers)
    report_title TEXT,
    type        TEXT,   -- sha256 | sha1 | md5 | ip | domain | url | ip:port
    value       TEXT,
    malware     TEXT,
    first_seen  TEXT,
    UNIQUE(source, report_url, type, value)
);
CREATE INDEX IF NOT EXISTS idx_iocs_seen ON iocs(first_seen);

-- Research pages already scanned for IOCs, so each is downloaded only once
CREATE TABLE IF NOT EXISTS ioc_pages (url TEXT PRIMARY KEY, scanned_at TEXT, found INTEGER);

-- Articles deleted after KEEP_DAYS. Some feeds keep old items for months and give them no date
-- (the pipeline then dates them when first seen); without this list they'd come back as "new".
CREATE TABLE IF NOT EXISTS forgotten (id TEXT PRIMARY KEY, pruned_at TEXT);

CREATE TABLE IF NOT EXISTS fetch_log (
    run_at   TEXT, site TEXT, source TEXT, status TEXT,
    items    INTEGER, new INTEGER, dupes INTEGER, old INTEGER, error TEXT
);
"""


def connect() -> sqlite3.Connection:
    """Open (or create) the database file and make sure the tables exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # rows behave like dicts: row["title"]
    conn.executescript(SCHEMA)
    upgrade(conn)
    return conn


SCHEMA_VERSION = 2      # bump when the labels below change, so stored articles get relabelled


def upgrade(conn):
    """
    A database made by an older version lacks newer columns. Add them, and fill them in, so
    nobody has to delete their database. (This is called a "migration".)
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(articles)")}
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if "kind" not in cols:
        from content import kind_of            # news / opinion / analysis
        conn.execute("ALTER TABLE articles ADD COLUMN kind TEXT DEFAULT 'news'")
        rows = conn.execute("SELECT id, site, source, url, title FROM articles").fetchall()
        conn.executemany("UPDATE articles SET kind=? WHERE id=?", [(kind_of(dict(r)), r["id"]) for r in rows])
        conn.commit()
        print(f"Database upgraded: labelled {len(rows)} stored articles as news / opinion / analysis")
    if version < 2:
        # Version 2 added "offtopic" (sport, entertainment...). Only articles labelled news are
        # re-checked, so labels that came from RSS categories at download time are kept.
        from content import kind_of
        rows = conn.execute("SELECT id, site, source, url, title FROM articles WHERE COALESCE(kind, 'news') = 'news'").fetchall()
        changed = [(k, r["id"]) for r in rows if (k := kind_of(dict(r))) != "news"]
        conn.executemany("UPDATE articles SET kind=? WHERE id=?", changed)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        if changed:
            print(f"Database upgraded: {len(changed)} stored articles relabelled (off-topic, opinion or analysis)")


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
    if conn.execute("SELECT 1 FROM articles WHERE id=? UNION ALL SELECT 1 FROM forgotten WHERE id=?",
                    (art["id"], art["id"])).fetchone():
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
    """Delete articles and logs older than KEEP_DAYS so the database stays small. Their ids are remembered."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    conn.execute("INSERT OR IGNORE INTO forgotten(id, pruned_at) SELECT id, ? FROM articles WHERE published < ?",
                 (now.isoformat(timespec="seconds"), cutoff))
    n = conn.execute("DELETE FROM articles WHERE published < ?", (cutoff,)).rowcount
    conn.execute("DELETE FROM fetch_log WHERE run_at < ?", (cutoff,))
    conn.execute("DELETE FROM forgotten WHERE pruned_at < ?", ((now - timedelta(days=REMEMBER_DAYS)).isoformat(),))
    return n
