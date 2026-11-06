"""
check_sources.py - health check for every feed in config/.

Usage (run from the repo folder):
  python pipeline/check_sources.py                 # check every enabled source on every site
  python pipeline/check_sources.py --site cyber    # just one site
  python pipeline/check_sources.py --all           # include disabled sources too
  python pipeline/check_sources.py --discover https://www.example.com
                                                   # find the feed for a new website

What it does, in order:
  1. Validates the YAML (missing fields, typos in region names, duplicates).
  2. Downloads every feed in parallel (16 at a time) and parses it.
  3. Prints one line per source: OK/FAIL, item count, date of the newest item.
  4. Flags "stale" feeds whose newest item is older than 14 days.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from config import load_sources, sites, validate
from feeds import check_feed, discover_feed

STALE_AFTER = timedelta(days=14)


def run_checks(site_filter: str | None, include_disabled: bool) -> int:
    chosen = [site_filter] if site_filter else sites()

    # 1. Validate config first: no point fetching if the file has mistakes.
    problems = [p for s in chosen for p in validate(s)]
    if problems:
        print("Config problems:")
        for p in problems:
            print("  -", p)
        print()

    sources = [s for site in chosen for s in load_sources(site, include_disabled) if s.get("feed")]
    print(f"Checking {len(sources)} feeds across {', '.join(chosen)}...\n")

    # 2. Fetch in parallel. Network calls spend most of their time waiting,
    #    so running 16 at once makes this ~16x faster than one by one.
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda s: (s, check_feed(s["feed"])), sources))

    # 3. Report
    now = datetime.now(timezone.utc)
    ok = stale = 0
    for s, r in sorted(results, key=lambda x: (x[0]["site"], not x[1]["ok"], x[0]["name"].lower())):
        group = s.get("region") or s.get("section") or ""
        if r["ok"]:
            ok += 1
            newest = r["newest"][:10] if r["newest"] else "no dates"
            flag = ""
            if r["newest"] and now - datetime.fromisoformat(r["newest"]) > STALE_AFTER:
                flag, stale = "  <- stale", stale + 1
            print(f"  OK    {s['site']:<5} {group:<9} {s['name'][:34]:<35} {r['items']:>4} items, newest {newest}{flag}")
        else:
            print(f"  FAIL  {s['site']:<5} {group:<9} {s['name'][:34]:<35} {r['error']}")

    print(f"\n{ok}/{len(results)} feeds OK, {stale} stale, {len(results) - ok} failing.")
    return 0 if ok == len(results) else 1


def run_discover(url: str) -> int:
    print(f"Looking for a feed on {url} ...")
    d = discover_feed(url)
    if not d["feed"]:
        print(f"Result: {d['how']}.")
        print("Tip: try a Google News search feed instead, e.g.")
        host = url.split("//")[-1].split("/")[0].removeprefix("www.")
        print(f'  https://news.google.com/rss/search?q=site:{host}&hl=en-US&gl=US&ceid=US:en')
        return 1
    c = d["check"]
    print(f"Found it ({d['how']}): {d['feed']}")
    print(f"  {c['items']} items, newest {c['newest']}, title: {c['title']}")
    print("\nPaste this into config/<site>/sources.yaml and fill in the blanks:")
    print(f'  - {{name: {c["title"] or "NAME"}, feed: "{d["feed"]}", region: REGION, type: TYPE, lang: en}}')
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Check the health of every RSS source.")
    ap.add_argument("--site", choices=sites(), help="only check one site")
    ap.add_argument("--all", action="store_true", help="include disabled sources")
    ap.add_argument("--discover", metavar="URL", help="find the feed for a website")
    a = ap.parse_args()
    sys.exit(run_discover(a.discover) if a.discover else run_checks(a.site, a.all))
