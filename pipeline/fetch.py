"""
fetch.py - download every feed and save new articles to the database.

Usage (from the repo folder):
  python pipeline/fetch.py              # all sites
  python pipeline/fetch.py --site geo   # one site

Run it as often as you like: articles already stored are skipped, so running it
twice in a row adds (almost) nothing the second time. That property has a name,
"idempotent", and it's what makes a pipeline safe to re-run after a failure.

The flow:
  1. Load enabled sources from config/<site>/sources.yaml          (config.py)
  2. Download all feeds in parallel, using ETag/Last-Modified       (feeds.py)
  3. Turn each entry into a clean article record                   (normalize.py)
  4. Insert new ones, skip ones we've seen, skip duplicate stories  (store.py)
  5. Log what happened per feed, delete articles older than 30 days
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import store
from config import load_sources, sites
from feeds import fetch, parse_feed_bytes, short_error
from normalize import normalize_entry

WINDOW_DAYS = 3   # ignore items older than this. Some feeds hold months of archive (Atlantic Council: 100 items).


def download(source: dict, state: dict | None) -> dict:
    """Runs in a worker thread: network only, no database (SQLite connections can't be shared across threads)."""
    state = state or {}
    try:
        r = fetch(source["feed"], etag=state.get("etag"), modified=state.get("modified"))
        if r.status_code == 304:
            return {"status": "unchanged"}
        if r.status_code != 200:
            return {"status": "error", "error": f"HTTP {r.status_code}"}
        parsed = parse_feed_bytes(r.content)
        if not parsed:
            return {"status": "error", "error": "not a feed"}
        return {"status": "ok", "entries": parsed.entries, "host": urlsplit(r.url).netloc,
                "etag": r.headers.get("ETag"), "modified": r.headers.get("Last-Modified")}
    except Exception as ex:
        return {"status": "error", "error": short_error(ex)}


def run(site_filter: str | None = None) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    run_at = now.isoformat()
    too_old = now - timedelta(days=WINDOW_DAYS)

    conn = store.connect()
    states = store.feed_states(conn)
    sources = [s for site in ([site_filter] if site_filter else sites()) for s in load_sources(site) if s.get("feed")]
    print(f"Fetching {len(sources)} feeds...")

    # Step 2: network in parallel
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda s: download(s, states.get(s["feed"])), sources))

    # Steps 3-5: database work, one feed at a time, in this (main) thread
    totals = {"new": 0, "seen": 0, "dupe": 0, "old": 0, "ok": 0, "unchanged": 0, "error": 0}
    per_site_new: dict[str, int] = {}
    for src, res in zip(sources, results):
        status = res["status"]
        totals[status] += 1
        counts = {"new": 0, "seen": 0, "dupe": 0, "old": 0}

        if status == "ok":
            for entry in res["entries"]:
                art = normalize_entry(entry, src, res["host"], now)
                if art is None:
                    continue
                if datetime.fromisoformat(art["published"]) < too_old:
                    counts["old"] += 1
                    continue
                counts[store.insert_article(conn, art)] += 1
            store.save_feed_state(conn, src["feed"], True, run_at, res.get("etag"), res.get("modified"))
        elif status == "unchanged":
            store.save_feed_state(conn, src["feed"], True, run_at,
                                  states[src["feed"]].get("etag"), states[src["feed"]].get("modified"))
        else:
            store.save_feed_state(conn, src["feed"], False, run_at, error=res["error"])
            print(f"  FAIL  {src['site']:<5} {src['name']}: {res['error']}")

        store.log_fetch(conn, run_at=run_at, site=src["site"], source=src["name"], status=status,
                        items=len(res.get("entries", [])), new=counts["new"], dupes=counts["dupe"],
                        old=counts["old"], error=res.get("error"))
        for k in counts:
            totals[k] += counts[k]
        per_site_new[src["site"]] = per_site_new.get(src["site"], 0) + counts["new"]

    pruned = store.prune(conn)
    conn.commit()   # nothing is saved to the file until we commit
    conn.close()

    print(f"\nFeeds:    {totals['ok']} downloaded, {totals['unchanged']} unchanged (304), {totals['error']} failed")
    print(f"Articles: {totals['new']} new ({', '.join(f'{k} {v}' for k, v in per_site_new.items())}), "
          f"{totals['seen']} already stored, {totals['dupe']} duplicate stories, "
          f"{totals['old']} older than {WINDOW_DAYS} days")
    if pruned:
        print(f"Pruned:   {pruned} articles older than {store.KEEP_DAYS} days")
    return totals


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch all feeds and store new articles.")
    ap.add_argument("--site", choices=sites())
    run(ap.parse_args().site)
