"""
export.py - write the small JSON files the website reads.

Usage:
  python pipeline/export.py            # today's files for every site
  python pipeline/export.py --site geo

This is the "contract" between the pipeline and the website. The website never touches the
database or the state files; it only reads what this script writes into site/data/:

  site/data/index.json              which sites exist and which dates are available
  site/data/<site>/<date>.json      one day's brief for one site
  site/data/toolkit.json            the Toolkit page links
  site/feeds/                       RSS and CSV for other tools such as OpenCTI (machine_feeds.py)

Each daily file is a snapshot: tomorrow's run writes a new file and leaves this one alone,
so the date picker on the site can show any previous day exactly as it was.

Nothing in here is written by AI. BLUF lines are taken from reports that already passed
the guardrails, and ranking is by how many outlets reported a story.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import content
import countries as gazetteer
import store
from config import CONFIG, ROOT, load_site, load_sources, load_yaml, sites
from industries import Industry, load_industries
from narratives import load_state, overlap, publisher, strip_links, words

SITE = ROOT / "site"
DATA = SITE / "data"
TOP_N = 5          # "Most reported today"
BLUF_N = 5         # bullets in the BLUF
HEADLINES_N = 40   # per headline list on the cyber page

# Headline lists (Cyber page) are configured in config/<site>/site.yaml under "lists:".


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # compact separators keep the files small; the site doesn't care about pretty printing
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def window_for(cfg: dict, date: str) -> tuple[int, str]:
    """
    How many days this brief covers, and the first day. Normally 1 (just today). On a catch-up
    day set in site.yaml (catch_up_days: {monday: 4}) it covers Friday to Monday, so nothing
    reported over the weekend is missed. Every report and article carries the date it arrived,
    so this is just counting over a longer window: nothing is re-run.
    """
    weekday = datetime.fromisoformat(date).strftime("%A").lower()
    days = max(1, int((cfg.get("catch_up_days") or {}).get(weekday, 1)))
    return days, (datetime.fromisoformat(date) - timedelta(days=days - 1)).date().isoformat()


def story_for_site(n: dict, start: str, kinds: dict[str, str]) -> dict:
    """
    Only the fields the website needs, counted over the brief's window (start .. today).
    Opinion and analysis pieces are left out of the story, its counts and its reports
    (content.split_story); they're listed separately under "Opinion and analysis".
    """
    news, comment, keep, _ = content.split_story(n, kinds)
    n = n | {"articles": news, "reports": keep,
             "article_count": max(len(news), n.get("article_count", 0) - len(comment))}
    arts = [a for a in n.get("articles", []) if (a.get("added") or "") >= start]
    reps = [r for r in n.get("reports", []) if r["date"] >= start]
    outlets = {a.get("publisher") or publisher(a["outlet"]) for a in arts} | {o for r in reps for o in r.get("outlets", [])}
    out = {k: n.get(k) for k in ("id", "group", "title", "first_seen", "last_updated", "article_count")}
    out.update(
        status="new" if n["first_seen"] >= start else "updated" if n["last_updated"] >= start else "unchanged",
        outlets_period=len(outlets),
        articles_period=len(arts),
        single_source=len(outlets) == 1,
        state_media_only=bool(arts) and all(a.get("type") == "state-media" for a in arts),
    )
    out["reports"] = [{k: r[k] for k in ("date", "text", "outlets")} for r in n.get("reports", [])]
    out["articles"] = [{k: a.get(k) for k in ("title", "outlet", "url", "published", "type", "lang", "added")}
                       for a in n.get("articles", [])]
    return out


def bluf(stories: list[dict], start: str) -> list[dict]:
    """
    Bottom line up front, assembled, not written: for the most reported stories today, take
    the first report that passed the guardrails. If a story has no checked report, use a real
    headline instead. No new AI text is created here.
    """
    lines = []
    for s in stories[:BLUF_N]:
        todays = [r for r in s["reports"] if r["date"] >= start]   # newest first
        if todays:
            lines.append({"story": s["id"], "title": s["title"], "text": todays[0]["text"], "kind": "report"})
        elif s["articles"]:
            a = s["articles"][0]
            lines.append({"story": s["id"], "title": s["title"], "kind": "headline",
                          "text": f"[{a['outlet']}]({a['url']}): {a['title']}"})
    return lines


def headline_lists(conn, site: str, cfg: dict, date: str, window: int = 1) -> list[dict]:
    """Plain headline lists per section, straight from the feeds (no AI at all). Set in site.yaml."""
    out = []
    for lst in cfg.get("lists", []):
        days, limit = max(lst.get("days", 2), window), lst.get("limit", HEADLINES_N)
        since = (datetime.fromisoformat(date) - timedelta(days=days - 1)).isoformat()
        rows = conn.execute(
            """SELECT title, outlet, url, published, type, kind FROM articles
               WHERE site=? AND section=? AND published >= ? ORDER BY published DESC LIMIT ?""",
            (site, lst["section"], since, limit)).fetchall()
        out.append({"id": lst["section"], "name": lst["name"], "days": days, "items": [dict(r) for r in rows]})
    return out


def guardrail_stats(site: str, start: str) -> dict:
    path = ROOT / "state" / site / "audit.json"
    removed = [e for e in json.loads(path.read_text(encoding="utf-8"))
               if e["date"] >= start and e.get("text")] if path.exists() else []   # only real sentences
    return {"removed": len(removed)}


def export_site(site: str, conn, date: str) -> str:
    cfg, state = load_site(site), load_state(site)
    days, start = window_for(cfg, date)
    recent = (datetime.fromisoformat(start) - timedelta(days=1)).date().isoformat()
    kinds = content.kinds_by_id(conn, [a for n in state["narratives"] for a in n["articles"]], site)
    stories = [story_for_site(n, start, kinds) for n in state["narratives"]]
    place_stories(site, stories)
    # Counted, not judged: most outlets in the window first, then most articles, then most overall
    stories.sort(key=lambda s: (-s["outlets_period"], -s["articles_period"], -s["article_count"]))
    active = [s for s in stories if s["status"] in ("new", "updated")]
    sources = load_sources(site)
    countries, headlines = country_summary(conn, site, stories, start, date)
    day = {
        "site": site,
        "name": cfg["name"],
        "date": date,
        "window": {"days": days, "start": start},
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "groups": [{"id": g["id"], "name": g["name"]} for g in cfg["groups"]],
        "pages": pages_for(cfg),
        "bluf": bluf(active, start),
        "top": [s["id"] for s in active[:TOP_N]],
        "stories": stories,
        "lists": headline_lists(conn, site, cfg, date, days),
        # Headline-type sections look back one extra day: the brief runs in the morning, so
        # "since midnight" would only be a few hours (and CISA usually adds to KEV in the US afternoon).
        "industries": industry_sections(conn, site, stories, start, recent),
        "vulns": vulnerabilities(conn, recent) if site == "cyber" else None,
        "iocs": indicators(conn, date, start) if site == "cyber" else None,
        "commentary": commentary(conn, site, cfg, state, kinds, recent),
        "countries": countries,
        "headlines": headlines,         # per-country headlines, in their own file
        "stats": {"sources": len(sources),
                  "reports": sum(1 for s in stories for r in s["reports"] if r["date"] >= start),
                  **guardrail_stats(site, start)},
    }
    path = DATA / site / f"{date}.json"
    write_json(path, day)
    span = f" (catch-up: {days} days from {start})" if days > 1 else ""
    return f"{path.relative_to(ROOT)}: {len(stories)} stories, {len(day['bluf'])} BLUF lines{span}"


# ── Pages and opinion ──────────────────────────────────────────────────────

# What a page can show, top to bottom (set per page in config/<site>/site.yaml under "pages:")
BLOCKS = {"bluf", "top", "stories", "regions", "countries", "commentary", "industries", "vulns", "iocs"}
COMMENTARY_N = 30        # opinion and analysis pieces listed per group


def pages_for(cfg: dict) -> list[dict]:
    """The sidebar: which pages exist and what each one shows. Checked here so a typo fails loudly."""
    groups = [g["id"] for g in cfg["groups"]]
    lists = [lst["section"] for lst in cfg.get("lists", [])]
    pages = cfg.get("pages") or ([{"id": "brief", "name": "Brief", "show": ["bluf", "top", "stories", "commentary"]}]
                                 + [{"id": f"list-{x}", "name": x.title(), "show": [f"list:{x}"]} for x in lists])
    seen, out = set(), []
    for p in pages:
        pid, show = str(p.get("id", "")), list(p.get("show") or [])
        problem = ("needs an id" if not pid else
                   "id can't look like a date" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", pid) else
                   "id is used twice" if pid in seen else
                   "id may only use a-z, 0-9 and -" if not re.fullmatch(r"[a-z0-9-]+", pid) else None)
        for b in show:
            kind, _, arg = b.partition(":")
            if not (b in BLOCKS or (kind == "group" and arg in groups) or (kind == "list" and arg in lists)):
                problem = f"unknown block '{b}' (use {sorted(BLOCKS)}, group:<id>, list:<section>)"
        if problem:
            raise SystemExit(f"config/{cfg['id']}/site.yaml, pages, '{pid or p}': {problem}")
        seen.add(pid)
        out.append({"id": pid, "name": p.get("name", pid), "show": show} | ({"icon": p["icon"]} if p.get("icon") else {}))
    return out


def commentary(conn, site: str, cfg: dict, state: dict, kinds: dict[str, str], since: str) -> list[dict]:
    """
    Opinion and analysis pieces (content.py), listed separately and labelled: never reports,
    never counted. Each is filed under a group: geo by its source's region, cyber by its section.
    """
    group_of_section = {sec: g["id"] for g in cfg["groups"] for sec in g.get("sections", [])}
    default = cfg["groups"][0]["id"]
    rows = [dict(r) for r in conn.execute(
        """SELECT title, outlet, url, published, type, kind, region, section FROM articles
           WHERE site=? AND COALESCE(kind, 'news') != 'news' AND first_seen >= ? ORDER BY published DESC""",
        (site, since))]
    # Pieces that sat inside a story from before opinion was separated
    for n in state["narratives"]:
        for a in n["articles"]:
            if kinds.get(a.get("id"), "news") != "news" and (a.get("added") or "") >= since:
                rows.append(a | {"kind": kinds[a["id"]], "region": n["group"]})
    out, seen, per_group = [], set(), {}
    for r in sorted(rows, key=lambda r: r.get("published") or "", reverse=True):
        g = (r.get("region") if site == "geo" else group_of_section.get(r.get("section"))) or default
        g, found = subject_region(site, r["title"], g)          # geo: filed by what it's about
        if r["url"] in seen or per_group.get(g, 0) >= COMMENTARY_N:
            continue
        seen.add(r["url"])
        per_group[g] = per_group.get(g, 0) + 1
        out.append({k: r.get(k) for k in ("title", "outlet", "url", "published", "type", "kind")} | {"group": g, "countries": found})
    return out


# ── Countries and tiers ───────────────────────────────────────────────────

HOT_MIN = 8          # a hotspot needs at least this many headlines in the last 24 hours...
HOT_RATIO = 2.0      # ...and twice its daily average over the 7 days before
HEADS_N = 25         # "other headlines" kept per country, newest first


def place_stories(site: str, stories: list[dict]):
    """Add countries, region (by subject, not by outlet) and domestic/international to each story."""
    g = gazetteer.load(site)
    if not g:
        return
    for s in stories:
        texts = [strip_links(r["text"]) for r in s["reports"][:10]] + [a["title"] for a in s["articles"]]
        s.update(g.place(g.score(texts, s["title"]), s["group"], s["title"]))


def country_summary(conn, site: str, stories: list[dict], start: str, date: str) -> tuple[dict | None, str | None]:
    """
    Per country: how many news headlines mention it, whether that's unusually many (hotspot),
    and the headlines that aren't part of any story yet. Counted from the feeds, no AI.

    Up to 25 headlines per country, from the last 24 hours (or the whole catch-up
    window on a Monday). They go in their OWN file, site/data/<site>/headlines/<date>.json,
    which the website only downloads when you open a region page or search. Each headline is
    stored once, and countries point at it by number, since one headline often names several.
    """
    g = gazetteer.load(site)
    if not g:
        return None, None
    now = datetime.now(timezone.utc)
    day_ago, week_ago = (now - timedelta(days=1)).isoformat(), (now - timedelta(days=8)).isoformat()
    since = min(day_ago, start)                       # 24 hours, or the catch-up window if longer
    oldest = conn.execute("SELECT MIN(published) FROM articles WHERE site=?", (site,)).fetchone()[0] or now.isoformat()
    history = (now - datetime.fromisoformat(oldest)).days >= 4          # enough days to know what's "normal"
    in_story = {a["url"] for s in stories for a in s["articles"]}
    last24, before, heads = Counter(), Counter(), {}
    for r in conn.execute("""SELECT title, outlet, url, published, type FROM articles
                             WHERE site=? AND COALESCE(kind, 'news')='news' AND published >= ?
                             ORDER BY published DESC""", (site, week_ago)):
        hits = [c for c, w in g.find(r["title"]).items() if w >= 1]       # venues alone don't count
        for c in hits:
            (last24 if r["published"] >= day_ago else before)[c] += 1
            if r["published"] >= since and r["url"] not in in_story:
                heads.setdefault(c, []).append(dict(r))
    wanted = set(last24) | set(heads) | {c for s in stories for c in s.get("countries", [])} \
        | {c for c in g.countries if g.tier(c, "regional") == 1}
    out, items, index, by_country = {}, [], {}, {}
    for c in wanted:
        info = g.countries[c]
        avg = before[c] / 7 if history else None
        mine, keys = [], set()
        for a in heads.get(c, []):                     # collapse the same headline from several feeds
            key = re.sub(r"[^a-z0-9]+", "", a["title"].lower())[:60]
            if key not in keys:
                keys.add(key)
                mine.append(a)
        for a in mine[:HEADS_N]:
            if a["url"] not in index:
                index[a["url"]] = len(items)
                items.append({k: a[k] for k in ("title", "outlet", "url", "published")} | ({"type": a["type"]} if a["type"] == "state-media" else {}))
            by_country.setdefault(c, []).append(index[a["url"]])
        out[c] = {"name": info["name"], "region": info["region"],
                  "global": g.tier(c, "global"), "regional": g.tier(c, "regional"),
                  "last24": last24[c], "avg7": round(avg, 1) if avg is not None else None,
                  "hotspot": bool(avg is not None and last24[c] >= HOT_MIN and last24[c] >= HOT_RATIO * max(avg, 1)),
                  "heads_total": len(mine), "heads_shown": min(len(mine), HEADS_N)}
    path = DATA / site / "headlines" / f"{date}.json"
    write_json(path, {"since": since, "items": items, "by_country": by_country})
    return out, f"data/{site}/headlines/{date}.json"


def subject_region(site: str, title: str, fallback: str) -> tuple[str, list[str]]:
    """Where an opinion piece belongs, by the countries in its headline (same idea as for stories)."""
    g = gazetteer.load(site)
    if not g:
        return fallback, []
    found = [c for c, w in g.find(title).items() if w >= 1]
    regions = {g.region(c) for c in found}
    return (regions.pop() if len(regions) == 1 else "global" if regions else fallback), found


# ── Cyber extras ───────────────────────────────────────────────────────────

CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)
IOC_ITEMS_SHOWN = 300     # per report on the page; the CSV download has all of them


def industry_sections(conn, site: str, stories: list[dict], start: str, recent: str) -> list[dict]:
    """Items about each industry (config/<site>/industries.yaml) from EVERY source, matched by keywords."""
    out = []
    rows = [dict(r) for r in conn.execute(
        """SELECT site, section, outlet, title, summary, url, published, type, kind FROM articles
           WHERE published >= ? AND NOT (site = 'cyber' AND section = 'advisories')""", (recent,))]   # bulletins have their own page
    for cfg in load_industries(site):
        ind = Industry(cfg)
        hits = [r for r in rows if ind.matches(r["title"], r["summary"], r["site"] == "cyber" and r["section"] in ("news", "intel"))]
        groups = []   # collapse near-identical headlines (four outlets, one airspace incursion) into one line
        for a in sorted(hits, key=lambda a: a["published"], reverse=True):
            w = words(a["title"])
            same = next((g for g in groups if overlap(w, g["w"]) >= 0.6), None)
            if same:
                same["similar"] += 1
            else:
                groups.append({"w": w, "item": a, "similar": 0})
        items = [{k: g["item"][k] for k in ("title", "outlet", "url", "published", "type", "kind")} | {"similar": g["similar"]}
                 for g in groups][:60]
        ids = [s["id"] for s in stories if s["status"] != "unchanged" and ind.matches(
            s["title"], " ".join([strip_links(r["text"]) for r in s["reports"] if r["date"] >= start]
                                 + [a["title"] for a in s["articles"]]), True)]
        out.append({"id": ind.id, "name": ind.name, "stories": ids, "items": items})
    return out


def vulnerabilities(conn, start: str) -> dict:
    """Newly added to CISA KEV in this window, and CVE numbers mentioned in the cyber news."""
    cols = "cve, vendor, product, name, description, date_added, due_date, ransomware"

    def short(row):
        d = dict(row)
        if len(d.get("description") or "") > 280:
            d["description"] = d["description"][:280].rsplit(" ", 1)[0] + "…"
        return d
    kev_new = [short(r) for r in conn.execute(f"SELECT {cols} FROM kev WHERE date_added >= ? ORDER BY date_added DESC, cve", (start,))]
    mentions: dict[str, list[dict]] = {}
    for r in conn.execute("SELECT title, summary, url, outlet, published FROM articles WHERE site='cyber' AND published >= ?", (start,)):
        for cve in {m.upper() for m in CVE_RE.findall(f"{r['title']} {r['summary'] or ''}")}:
            mentions.setdefault(cve, []).append(dict(r))
    kev = {}
    if mentions:
        marks = ",".join("?" * len(mentions))
        kev = {r["cve"]: short(r) for r in conn.execute(f"SELECT {cols} FROM kev WHERE cve IN ({marks})", list(mentions))}
    in_news = [{"cve": cve, "outlets": len({publisher(a["outlet"]) for a in arts}),
                "articles": [{k: a[k] for k in ("title", "url", "outlet")} for a in sorted(arts, key=lambda a: a["published"], reverse=True)[:3]],
                "kev": kev.get(cve)} for cve, arts in mentions.items()]
    in_news.sort(key=lambda c: (-c["outlets"], c["kev"] is None, c["cve"]))
    return {"kev_new": kev_new, "in_news": in_news[:40]}


def indicators(conn, date: str, start: str) -> dict:
    """IOCs collected by indicators.py in this window. Values are already defanged."""
    rows = [dict(r) for r in conn.execute("SELECT * FROM iocs WHERE first_seen >= ? ORDER BY first_seen DESC", (start,))]
    groups: dict[tuple, dict] = {}
    for r in rows:
        g = groups.setdefault((r["source"], r["report_url"], r["report_title"]), {   # trackers: one card per threat type
            "source": r["source"], "url": r["report_url"], "title": r["report_title"],
            "first_seen": r["first_seen"], "counts": {}, "items": {}, "kind": "report" if r["report_url"] else "tracker"})
        g["counts"][r["type"]] = g["counts"].get(r["type"], 0) + 1
        lst = g["items"].setdefault(r["type"], [])
        if len(lst) < IOC_ITEMS_SHOWN:
            lst.append(r["value"] + (f"  ({r['malware']})" if r["malware"] else ""))
    path = DATA / "cyber" / f"iocs-{date}.csv"       # full download for analysts and tools
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["first_seen", "source", "report_title", "report_url", "type", "value_defanged", "malware"])
        w.writerows([r["first_seen"], r["source"], r["report_title"], r["report_url"], r["type"], r["value"], r["malware"] or ""] for r in rows)
    ordered = sorted(groups.values(), key=lambda g: (g["kind"] != "report", -sum(g["counts"].values())))
    return {"groups": ordered, "total": len(rows), "csv": f"data/cyber/iocs-{date}.csv" if rows else None}


def prune_old(site: str, today: str) -> int:
    """
    Keep only the last keep_days of daily files on the website (site.yaml, default 365).
    Older briefs, their headlines files and IOC CSVs are deleted. Git still remembers them (every
    commit is kept), so nothing is truly lost: "git log -- site/data/geo/2026-01-05.json" finds one.
    """
    keep = int(load_site(site).get("keep_days", 365))
    cutoff = (datetime.fromisoformat(today) - timedelta(days=keep)).date().isoformat()
    gone = 0
    for path in [*(DATA / site).glob("20*.json"), *(DATA / site / "headlines").glob("20*.json"), *(DATA / site).glob("iocs-20*.csv")]:
        day = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
        if day and day.group(1) < cutoff:
            path.unlink()
            gone += 1
    return gone


def write_index(extra: dict | None = None):
    """List every site and every date that has a file, newest first."""
    index = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sites": {},
             "max_range_days": 14,     # how many days the calendar may combine
             "repo": os.environ.get("GITHUB_REPOSITORY")}   # "owner/name" on GitHub, for the Sources page's links
    labels = {"geo": "Geopolitical", "cyber": "Cyber"}
    for site in sites():
        dates = sorted((p.stem for p in (DATA / site).glob("20*.json")), reverse=True)
        if dates:
            index["sites"][site] = {"label": labels.get(site, load_site(site)["name"]), "dates": dates}
    write_json(DATA / "index.json", index | (extra or {}))


def write_sources(conn):
    """
    site/data/sources.json, the website's Sources page. For every source in the config
    (enabled or not): where it belongs, and how it's doing according to the database:
    the last successful download, failures in a row, and articles in the last 7 days.
    """
    from config import load_sources
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    state = {r["feed"]: dict(r) for r in conn.execute("SELECT * FROM feed_state")}
    counts = {(r[0], r[1]): (r[2], r[3]) for r in conn.execute(
        "SELECT site, source, COUNT(*), MAX(published) FROM articles WHERE published >= ? GROUP BY site, source", (week,))}
    out = []
    for site in sites():
        for s in load_sources(site, include_disabled=True):
            st = state.get(s.get("feed") or "", {})
            n, newest = counts.get((site, s["name"]), (0, None))
            status = ("disabled" if not s.get("enabled", True) else "no feed" if not s.get("feed") else
                      "failing" if st.get("fails_in_row") else "new" if not st else "quiet" if n == 0 else "ok")
            out.append({"site": site, "name": s["name"], "feed": s.get("feed") or s.get("site"),
                        "where": s.get("region") or s.get("section"), "type": s.get("type"), "lang": s.get("lang"),
                        "kind": s.get("kind"), "status": status, "articles_7d": n, "newest": newest,
                        "last_ok": st.get("last_ok"), "fails": st.get("fails_in_row") or 0,
                        "error": st.get("last_error"), "note": s.get("note")})
    write_json(DATA / "sources.json", {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": out})
    return out


def write_toolkit():
    path = CONFIG / "geo" / "toolkit.yaml"
    write_json(DATA / "toolkit.json", load_yaml(path) if path.exists() else {"groups": []})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Write the website's JSON files.")
    ap.add_argument("--site", choices=sites())
    ap.add_argument("--date", help="label the export with this date (default: today, UTC)")
    a = ap.parse_args()
    date = a.date or datetime.now(timezone.utc).date().isoformat()
    conn = store.connect()
    for s in [a.site] if a.site else sites():
        print("Wrote", export_site(s, conn, date))
        if (n := prune_old(s, date)):
            print(f"Removed {n} files older than {load_site(s).get('keep_days', 365)} days from site/data/{s}/")
    srcs = write_sources(conn)
    conn.close()
    bad = sum(1 for x in srcs if x["status"] == "failing")
    write_index({"sources_failing": bad})
    write_toolkit()
    print(f"Wrote site/data/index.json, toolkit.json and sources.json ({len(srcs)} sources, {bad} failing)")
    try:                                   # RSS, CSV and STIX feeds for other tools (OpenCTI)
        import machine_feeds
        print(machine_feeds.run())
    except Exception as ex:                # a feed problem must never stop the website
        print(f"Machine feeds skipped: {ex}")
