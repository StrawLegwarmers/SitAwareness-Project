"""
normalize.py - turns a messy feed entry into a clean, predictable article record.

Every feed is a little different: some put HTML in the summary, some add tracking codes
to links, some have no date, some wrap other outlets' stories (Google News). This file
is where all those differences get flattened so the rest of the pipeline never has to care.
"""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from content import classify

# Query parameters that only exist for tracking. Real examples from our feeds:
#   aljazeera.com/...?traffic_source=rss     dw.com/...?maca=en-rss-en-all-1573-rdf
TRACKING_PARAMS = re.compile(
    r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|ocid|cmpid|traffic_source|maca|at_\w+|taid|ito|ref|rss|source|xtor|smid|partner)$",
    re.I,
)


def canonical_url(url: str) -> str:
    """
    One article can arrive with different URLs:
        http://www.dw.com/en/story/a-123?maca=en-rss
        https://www.dw.com/en/story/a-123
    Both should count as the same article. We lowercase the host, force https, drop
    tracking parameters, the #fragment and any trailing slash.
    """
    p = urlsplit(url.strip())
    host = p.netloc.lower()
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)])
    path = p.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))


def clean_text(raw: str | None, limit: int = 500) -> str:
    """Strip HTML tags and entities from a summary and cut it to `limit` characters at a word boundary."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)          # remove tags like <p> <img ...>
    text = html.unescape(text)                     # &amp; -> &, &#8217; -> ’
    text = re.sub(r"\s+", " ", text).strip()       # collapse whitespace
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def title_key(title: str) -> str:
    """
    A fingerprint of a headline for spotting the *same story at a different URL*
    (e.g. an AP story republished by several papers). Lowercase letters and digits only.
    """
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:120]


def entry_date(entry, now: datetime) -> datetime:
    """
    When was this published? Use the feed's date if it has one; otherwise 'now'
    (the first time we saw it). Dates in the future are timezone bugs: clamp them to now.
    """
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return now
    d = datetime(*t[:6], tzinfo=timezone.utc)
    return min(d, now)


def article_id(site: str, canon: str) -> str:
    """A short stable ID: the same site + URL always gives the same ID."""
    return hashlib.sha1(f"{site}|{canon}".encode()).hexdigest()[:16]


def normalize_entry(entry, source: dict, feed_host: str, now: datetime) -> dict | None:
    """Turn one feedparser entry into our article dict. Returns None if it's unusable."""
    title = clean_text(entry.get("title"), limit=300)
    link = (entry.get("link") or "").strip()
    if not title or not link.lower().startswith(("http://", "https://")):
        return None   # only ordinary web links; never "javascript:" or other schemes (security)

    outlet = source["name"]
    summary = clean_text(entry.get("summary") or entry.get("description"))

    # Google News search feeds wrap other outlets' stories. The real publisher is in
    # <source>, and the headline ends with " - Publisher". Unwrap both.
    if feed_host.endswith("news.google.com"):
        src = entry.get("source") or {}
        if src.get("title"):
            outlet = src["title"]
            if title.endswith(" - " + outlet):
                title = title[: -len(" - " + outlet)]
        summary = ""  # Google's "summary" just repeats the headline as links

    canon = canonical_url(link)
    published = entry_date(entry, now)
    # News, opinion or analysis, from the outlet's own labels (config/content_types.yaml)
    tags = [t.get("term") or "" for t in entry.get("tags") or []]
    kind, _ = classify(link, title, tags, source)
    return {
        "id": article_id(source["site"], canon),
        "site": source["site"],
        "source": source["name"],
        "outlet": outlet,
        "url": link,
        "canonical_url": canon,
        "title": title,
        "title_key": title_key(title),
        "summary": summary,
        "published": published.isoformat(timespec="seconds"),
        "first_seen": now.isoformat(timespec="seconds"),
        "region": source.get("region"),
        "section": source.get("section"),
        "topics": ",".join(source.get("topics") or []),
        "lang": source.get("lang"),
        "type": source.get("type"),
        "kind": kind,
    }
