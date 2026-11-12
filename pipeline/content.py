"""
content.py - is this article news, opinion or analysis?

Usage:
  python pipeline/content.py            # how today's articles were labelled, with examples
  python pipeline/content.py --list opinion

Only NEWS is sent to the AI and counted as reporting. Opinion and analysis are kept and shown,
labelled, in their own block: an op-ed arguing that a leader "is not ready for peace" must never
become "Outlet X reported that the leader is not ready for peace".

No AI here. The rules live in config/content_types.yaml and use the outlet's own labels.
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from functools import lru_cache
from urllib.parse import urlsplit

from config import CONFIG, load_sources, load_yaml, sites

KINDS = ("news", "opinion", "analysis", "offtopic")
COMMENTARY = ("opinion", "analysis")      # shown, labelled, apart from reporting


@lru_cache(maxsize=1)
def rules() -> dict:
    path = CONFIG / "content_types.yaml"
    cfg = load_yaml(path) if path.exists() else {}
    out = {"source_types": cfg.get("source_types") or {},
           "news_tags": {t.lower().strip() for t in cfg.get("news_tags", [])}}
    for kind in ("offtopic", "opinion", "analysis"):
        r = cfg.get(kind) or {}
        out[kind] = {
            "sites": set(r.get("sites") or []),
            "tags": {t.lower().strip() for t in r.get("tags", [])},
            "url_parts": {p.lower().strip("/") for p in r.get("url_parts", [])},
            "starts": tuple(s.lower() for s in r.get("headline_starts", [])),
            "ends": tuple(s.lower() for s in r.get("headline_ends", [])),
            "patterns": [re.compile(p, re.I) for p in r.get("headline_patterns", [])],
        }
    terms = (cfg.get("offtopic") or {}).get("story_terms") or []
    out["offtopic"]["story_terms"] = re.compile(
        r"(?<![\w-])(?:" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")(?![\w-])", re.I) if terms else None
    out["offtopic"]["not_terms"] = re.compile(
        r"(?<![\w-])(?:" + "|".join(re.escape(t) for t in (cfg.get("offtopic") or {}).get("not_story_terms") or []) + r")(?![\w-])",
        re.I) if (cfg.get("offtopic") or {}).get("not_story_terms") else None
    return out


def offtopic_story(title: str, headlines: list[str], site: str) -> bool:
    """
    A NEW story the AI proposed that is really entertainment or sport (a film festival, an actor's
    death, a transfer), recognised by words in its title or in half of its headlines
    (content_types.yaml, offtopic: story_terms). The articles stay in the database; no story is made.
    """
    r = rules()["offtopic"]
    if not r.get("story_terms") or (r["sites"] and site not in r["sites"]):
        return False

    def hit(text):
        text = r["not_terms"].sub(" ", text) if r.get("not_terms") else text
        return bool(r["story_terms"].search(text))
    if hit(title or ""):
        return True
    heads = [h for h in headlines if h]
    return bool(heads) and sum(hit(h) for h in heads) * 2 >= len(heads)


@lru_cache(maxsize=1)
def source_settings() -> dict[tuple[str, str], dict]:
    """{(site, source name): source} for looking up a source's own 'kind' or 'type'."""
    return {(s["site"], s["name"]): s for site in sites() for s in load_sources(site, include_disabled=True)}


def classify(url: str, title: str, tags: list[str] | None = None, source: dict | None = None,
             site: str | None = None) -> tuple[str, str]:
    """Returns (kind, reason). reason says which rule matched, so a wrong label is easy to trace."""
    source = source or {}
    if source.get("kind") in KINDS:
        return source["kind"], "source setting"
    R = rules()
    folders = [p for p in urlsplit(url or "").path.lower().split("/") if p][:-1]   # not the last part (the slug)
    head = (title or "").lower().strip()
    tags = [t for t in (tags or []) if t and t.strip()]
    if any(t.lower().strip() in R["news_tags"] for t in tags):
        tags = []                           # tagged "News" AND "Opinion": let the address and headline decide
    site = site or source.get("site")
    for kind in ("offtopic", "opinion", "analysis"):
        r = R[kind]
        if r["sites"] and site not in r["sites"]:
            continue
        tag = next((t for t in tags if t.lower().strip() in r["tags"]), None)
        if tag:
            return kind, f"RSS category '{tag}'"
        part = next((p for p in folders if p in r["url_parts"]), None)
        if part:
            return kind, f"address /{part}/"
        if head.startswith(r["starts"]) or head.endswith(r["ends"]) or any(p.search(head) for p in r["patterns"]):
            return kind, "headline label"
    by_type = R["source_types"].get(source.get("type"))
    if by_type in KINDS:
        return by_type, f"source type {source.get('type')}"
    return "news", ""


def kind_of(article: dict, site: str | None = None) -> str:
    """Kind for an article record (from the database or a story), using its source's settings if known."""
    if article.get("kind") in KINDS:
        return article["kind"]
    site = site or article.get("site")
    src = source_settings().get((site, article.get("source") or article.get("outlet")))
    return classify(article.get("url", ""), article.get("title", ""), None, src, site)[0]


def kinds_by_id(conn, articles: list[dict], site: str) -> dict[str, str]:
    """{article id: kind} for a story's articles. The database knows best (it saw the RSS categories)."""
    ids = [a["id"] for a in articles if a.get("id")]
    known = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        known.update({r[0]: r[1] for r in conn.execute(
            f"SELECT id, kind FROM articles WHERE id IN ({','.join('?' * len(chunk))})", chunk)})
    return {a["id"]: known.get(a["id"]) or kind_of(a, site) for a in articles if a.get("id")}


def split_story(n: dict, kinds: dict[str, str]) -> tuple[list, list, list, list]:
    """
    Separate a story's reporting from its commentary:
      news articles | opinion/analysis articles | reports kept | reports dropped
    A report is dropped when every article it cites is opinion or analysis: "X reported that..."
    must rest on news. (Stories built by older versions can contain such reports.)
    """
    news = [a for a in n.get("articles", []) if kinds.get(a.get("id"), "news") == "news"]
    comment = [a | {"kind": kinds[a["id"]]} for a in n.get("articles", []) if kinds.get(a.get("id"), "news") in COMMENTARY]
    # off-topic articles (sport...) are simply dropped
    keep, drop = [], []
    for r in n.get("reports", []):
        cited = r.get("articles") or []
        (drop if cited and all(kinds.get(i, "news") != "news" for i in cited) else keep).append(r)
    return news, comment, keep, drop


def report(kind_filter: str | None = None):
    import store
    conn = store.connect()
    rows = conn.execute("SELECT site, source, title, url, kind FROM articles ORDER BY published DESC").fetchall()
    total = Counter(r["kind"] for r in rows)
    print(f"{len(rows)} articles: " + ", ".join(f"{total[k]} {k}" for k in KINDS))
    for kind in ([kind_filter] if kind_filter else ("offtopic", "opinion", "analysis")):
        picked = [r for r in rows if r["kind"] == kind]
        by_source = Counter(r["source"] for r in picked)
        print(f"\n{kind.upper()}: {len(picked)} from {len(by_source)} sources")
        for src, n in by_source.most_common(12):
            print(f"  {n:>4}  {src}")
        print("  examples:")
        for r in picked[: (60 if kind_filter else 8)]:
            src = source_settings().get((r["site"], r["source"]))
            print(f"    [{classify(r['url'], r['title'], None, src)[1] or 'RSS category'}] {r['source']}: {r['title'][:90]}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Show how articles were labelled news / opinion / analysis.")
    ap.add_argument("--list", choices=["offtopic", "opinion", "analysis"], help="list more examples of one kind")
    report(ap.parse_args().list)
