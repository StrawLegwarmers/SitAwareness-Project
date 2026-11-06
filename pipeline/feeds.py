"""
feeds.py - the low-level tools for talking to RSS/Atom feeds.

Two jobs live here:
  check_feed(url)    -> is this URL a working feed? how many items? how fresh?
  discover_feed(url) -> given a normal website URL, find its feed URL.

Everything else in the pipeline (fetching, storing, analysing) builds on these.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

import feedparser
import requests

# Identify ourselves politely. Some sites block requests with no User-Agent.
USER_AGENT = "SitAware/0.1 (open-source news reader; +https://github.com/)"
TIMEOUT = 20  # seconds

# Paths many sites use for their feed. Tried in order when a page has no <link> tag.
COMMON_FEED_PATHS = ["feed/", "rss/", "rss.xml", "feed.xml", "atom.xml", "index.xml", "?feed=rss2", "rss", "feed"]


def fetch(url: str, etag: str | None = None, modified: str | None = None) -> requests.Response:
    """
    Download a URL with our User-Agent and a timeout.

    etag / modified make it a *conditional* request: "send me this feed only if it changed
    since last time". If nothing changed, the server answers 304 Not Modified with no body,
    which saves both sides bandwidth. (Lesson 2.)
    """
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    return requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)


def short_error(ex: Exception) -> str:
    """Network errors from `requests` are very long. Keep just the useful part."""
    if isinstance(ex, (requests.Timeout, requests.ConnectionError)):
        return type(ex).__name__          # e.g. ConnectTimeout, ReadTimeout, SSLError
    return f"{type(ex).__name__}: {ex}"[:120]


def _newest(entries) -> str | None:
    """Return the newest published/updated date among feed entries, as ISO text."""
    best = None
    for e in entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if t:
            d = datetime(*t[:6], tzinfo=timezone.utc)
            if best is None or d > best:
                best = d
    return best.isoformat() if best else None


def parse_feed_bytes(content: bytes):
    """Parse raw bytes as a feed. Returns the feedparser result, or None if it isn't a feed."""
    parsed = feedparser.parse(content)
    # feedparser is forgiving: it will "parse" an HTML page into zero entries.
    # So we only accept it as a feed if it actually has items.
    if parsed.entries:
        return parsed
    return None


def check_feed(url: str) -> dict:
    """Fetch a feed URL and report on it. Never raises; errors go in the result."""
    result = {"url": url, "ok": False, "status": None, "items": 0, "newest": None, "title": None, "error": None}
    try:
        r = fetch(url)
        result["status"] = r.status_code
        if r.status_code != 200:
            result["error"] = f"HTTP {r.status_code}"
            return result
        parsed = parse_feed_bytes(r.content)
        if not parsed:
            result["error"] = "not a feed (no items found)"
            return result
        result.update(ok=True, items=len(parsed.entries), newest=_newest(parsed.entries),
                      title=parsed.feed.get("title"))
    except Exception as ex:  # network errors, timeouts, SSL problems...
        result["error"] = short_error(ex)
    return result


class _LinkFinder(HTMLParser):
    """Collects <link rel="alternate" type="application/rss+xml" href="..."> tags from a web page."""

    def __init__(self):
        super().__init__()
        self.found: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        if "alternate" in a.get("rel", "").lower() and re.search(r"(rss|atom)\+xml", a.get("type", ""), re.I):
            if a.get("href"):
                self.found.append(a["href"])


def discover_feed(site_url: str) -> dict:
    """
    Find the feed for a website. Strategy, cheapest first:
      1. Maybe the URL already IS a feed.
      2. Look in the page's HTML for <link rel="alternate" type="application/rss+xml">.
         This is the standard way sites advertise their feed (browsers and Feedly use it too).
      3. Guess common paths like /feed/ or /rss.xml.
    Returns {"site": ..., "feed": <url or None>, "how": <which step worked>, "check": <check_feed result>}
    """
    out = {"site": site_url, "feed": None, "how": None, "check": None}
    try:
        r = fetch(site_url)
    except Exception as ex:
        out["how"] = f"site unreachable: {type(ex).__name__}"
        return out

    # Step 1: already a feed?
    if r.status_code == 200 and parse_feed_bytes(r.content):
        out.update(feed=r.url, how="url is a feed", check=check_feed(r.url))
        return out

    # Step 2: advertised in the HTML
    candidates: list[str] = []
    if r.status_code == 200 and "html" in r.headers.get("content-type", "").lower():
        finder = _LinkFinder()
        try:
            finder.feed(r.text)
        except Exception:
            pass
        candidates += [urljoin(r.url, h) for h in finder.found]
    for c in candidates:
        chk = check_feed(c)
        if chk["ok"]:
            out.update(feed=c, how="<link> tag in page", check=chk)
            return out

    # Step 3: guess common paths
    base = r.url if r.url.endswith("/") else r.url + "/"
    for path in COMMON_FEED_PATHS:
        c = urljoin(base, path)
        chk = check_feed(c)
        if chk["ok"]:
            out.update(feed=c, how=f"guessed /{path}", check=chk)
            return out

    out["how"] = f"no feed found (site HTTP {r.status_code})"
    return out
