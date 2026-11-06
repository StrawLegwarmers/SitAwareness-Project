"""
stats.py - look inside the database.

Usage:
  python pipeline/stats.py                       # overview of both sites
  python pipeline/stats.py --site cyber --latest 20
  python pipeline/stats.py --search "Hormuz"     # headlines containing a word

Every number here comes from a plain SQL query. Read the queries; they're the
fastest way to learn SQL, and you'll write your own in the exercises.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import store


def show(conn, title: str, sql: str, params=()):
    rows = conn.execute(sql, params).fetchall()
    print(f"\n{title}")
    if not rows:
        print("  (none)")
    for r in rows:
        print("  " + "  ".join(str(v if v is not None else "") for v in r))


def main(site: str | None, latest: int, search: str | None):
    conn = store.connect()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    where, p = ("WHERE site=?", (site,)) if site else ("", ())
    and_site = "AND site=?" if site else ""

    show(conn, "Articles stored, by site:",
         f"SELECT site, COUNT(*) FROM articles {where} GROUP BY site", p)

    show(conn, "Last 24 hours, by region (geo) or section (cyber):",
         f"""SELECT site, COALESCE(region, section) AS grp, COUNT(*) AS n FROM articles
             WHERE published >= ? {and_site} GROUP BY site, grp ORDER BY site, n DESC""", (since, *p))

    show(conn, "Busiest sources, last 24 hours:",
         f"""SELECT COUNT(*) AS n, site, source FROM articles WHERE published >= ? {and_site}
             GROUP BY site, source ORDER BY n DESC LIMIT 10""", (since, *p))

    show(conn, "Feeds currently failing (fails in a row, last error):",
         """SELECT fails_in_row, feed, substr(last_error, 1, 60) FROM feed_state WHERE fails_in_row > 0
            ORDER BY fails_in_row DESC""")

    if search:
        show(conn, f'Headlines containing "{search}":',
             f"""SELECT substr(published,1,16), outlet, title FROM articles
                 WHERE title LIKE ? {and_site} ORDER BY published DESC LIMIT 25""", (f"%{search}%", *p))
    else:
        show(conn, f"Latest {latest} headlines:",
             f"""SELECT substr(published,1,16), outlet, title FROM articles {where}
                 ORDER BY published DESC LIMIT ?""", (*p, latest))
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Show what's in the database.")
    ap.add_argument("--site")
    ap.add_argument("--latest", type=int, default=10)
    ap.add_argument("--search")
    a = ap.parse_args()
    main(a.site, a.latest, a.search)
