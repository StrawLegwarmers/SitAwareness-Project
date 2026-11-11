"""
indicators.py - collect exploited vulnerabilities and indicators of compromise (IOCs).

Usage:
  python pipeline/indicators.py

Sources, all open:
  1. CISA KEV         vulnerabilities CISA has confirmed are exploited in the wild   (no key)
  2. Research reports IOCs that vendors publish at the end of their research posts   (no key)
                      (Talos, Unit 42, ESET, Check Point, DFIR Report... = the 'intel' sources)
  3. Feodo Tracker    botnet command-and-control servers currently online           (no key)
  4. ThreatFox        community IOC database from abuse.ch                           (OPTIONAL: free key
                      in the ABUSECH_AUTH_KEY secret; skipped if not set)

No AI is involved anywhere here: it's downloading and pattern matching.

SAFETY: every indicator is stored and shown DEFANGED (hxxp://, example[.]com, 1.2.3[.]4), so
nothing on the site is a working malicious link. Analysts "refang" a value only on purpose.
"""
from __future__ import annotations

import html
import ipaddress
import os
import re
from datetime import datetime, timedelta, timezone

import requests

import store
from feeds import USER_AGENT, short_error

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
FEODO_URL = "https://feodotracker.abuse.ch/downloads/ipblocklist.json"
THREATFOX_API = "https://threatfox-api.abuse.ch/api/v1/"
MAX_PAGES = 20          # research pages downloaded per run (be polite)
MAX_PER_REPORT = 500    # indicators kept per report
LOOKBACK_DAYS = 3       # scan research posts first seen in the last N days

# ── Patterns ────────────────────────────────────────────────────────────────
# Hashes are unambiguous. Network indicators are only taken when the report itself DEFANGED them
# ("[.]", "hxxp"): that's how researchers mark "this is an indicator", so ordinary links in the
# page (to the company's own site, social media...) are never mistaken for IOCs.
DOT = r"(?:\[\.\]|\(\.\)|\[dot\]|\.)"
DEF = r"(?:\[\.\]|\(\.\)|\[dot\])"
SHA256 = re.compile(r"(?<![a-fA-F0-9])[a-fA-F0-9]{64}(?![a-fA-F0-9])")
SHA1 = re.compile(r"(?<![a-fA-F0-9])[a-fA-F0-9]{40}(?![a-fA-F0-9])")
MD5 = re.compile(r"(?<![a-fA-F0-9])[a-fA-F0-9]{32}(?![a-fA-F0-9])")
IP_DEF = re.compile(rf"(?<![\d.])\d{{1,3}}{DOT}\d{{1,3}}{DOT}\d{{1,3}}{DOT}\d{{1,3}}(?![\d])")
URL_DEF = re.compile(r"\b(?:hxxps?|hXXps?|fxp)(?:\[:\]|:)//[^\s<>\"']+")
DOMAIN_DEF = re.compile(rf"\b(?:[a-z0-9-]+{DOT})*[a-z0-9-]+{DEF}[a-z]{{2,24}}\b", re.I)


# Hashes that appear in reports but aren't indicators (e.g. the hash of an EMPTY file).
NOT_IOCS = {"d41d8cd98f00b204e9800998ecf8427e", "da39a3ee5e6b4b0d3255bfef95601890afd80709",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}


def plain(v: str) -> str:
    """'example[.]com' -> 'example.com' (only used for checks, never displayed)."""
    return re.sub(DEF, ".", v).replace("[:]", ":").replace("hxxp", "http").replace("hXXp", "http")


def defang(v: str, kind: str) -> str:
    """Make any indicator safe to display: example.com -> example[.]com, http -> hxxp."""
    v = plain(v)
    if kind in ("sha256", "sha1", "md5"):
        return v.lower()
    if kind in ("url",):
        v = v.replace("http", "hxxp", 1)
    if kind in ("ip", "ip:port"):
        head, _, last = v.rpartition(".")
        return f"{head}[.]{last}"
    return re.sub(r"\.", "[.]", v) if kind in ("domain", "url") else v


def extract(text: str) -> dict[str, set[str]]:
    """Pull indicators out of a research report's text."""
    found = {"sha256": set(SHA256.findall(text)), "sha1": set(SHA1.findall(text)), "md5": set(MD5.findall(text))}
    found["url"] = {u.rstrip(".,;)]") for u in URL_DEF.findall(text)}
    ips = set()
    for m in IP_DEF.findall(text):
        if not re.search(DEF, m):
            continue                         # a plain 1.2.3.4 isn't marked as an IOC: skip
        try:
            ip = ipaddress.ip_address(plain(m))
            if ip.is_global:                 # skip private / example / reserved ranges
                ips.add(m)
        except ValueError:
            pass
    found["ip"] = ips
    found["domain"] = {d for d in DOMAIN_DEF.findall(text) if not re.fullmatch(rf"[\d{DOT}]+", d)}
    return {k: {defang(v, k) for v in vs} - NOT_IOCS for k, vs in found.items()}


def page_text(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
    r.raise_for_status()
    t = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", r.text, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", t))


# ── Sources ─────────────────────────────────────────────────────────────────

def update_kev(conn) -> str:
    data = requests.get(KEV_URL, headers={"User-Agent": USER_AGENT}, timeout=60).json()
    rows = [(v["cveID"], v.get("vendorProject"), v.get("product"), v.get("vulnerabilityName"),
             v.get("shortDescription"), v.get("dateAdded"), v.get("dueDate"), v.get("knownRansomwareCampaignUse"))
            for v in data.get("vulnerabilities", [])]
    conn.executemany("INSERT OR REPLACE INTO kev VALUES (?,?,?,?,?,?,?,?)", rows)
    latest = max((r[5] for r in rows), default="?")
    return f"CISA KEV: {len(rows)} exploited vulnerabilities in the catalog (latest added {latest})"


def research_iocs(conn, now: datetime) -> str:
    since = (now - timedelta(days=LOOKBACK_DAYS)).isoformat()
    todo = conn.execute(
        """SELECT url, title, outlet FROM articles
           WHERE site='cyber' AND section='intel' AND first_seen >= ?
             AND url NOT IN (SELECT url FROM ioc_pages) ORDER BY published DESC LIMIT ?""",
        (since, MAX_PAGES)).fetchall()
    total, reports = 0, 0
    for row in todo:
        try:
            found = extract(page_text(row["url"]))
        except Exception as ex:
            print(f"    could not read {row['url'][:70]}: {short_error(ex)}")
            conn.execute("INSERT OR REPLACE INTO ioc_pages VALUES (?,?,?)", (row["url"], now.isoformat(), -1))
            continue
        items = [(k, v) for k, vs in found.items() for v in sorted(vs)][:MAX_PER_REPORT]
        conn.executemany("INSERT OR IGNORE INTO iocs VALUES (?,?,?,?,?,?,?)",
                         [(row["outlet"], row["url"], row["title"], k, v, None, now.isoformat()) for k, v in items])
        conn.execute("INSERT OR REPLACE INTO ioc_pages VALUES (?,?,?)", (row["url"], now.isoformat(), len(items)))
        total += len(items)
        reports += bool(items)
    return f"Research reports: scanned {len(todo)} new pages, {reports} contained IOCs ({total} indicators)"


def feodo(conn, now: datetime) -> str:
    rows = requests.get(FEODO_URL, headers={"User-Agent": USER_AGENT}, timeout=30).json()
    online = [r for r in rows if r.get("status") == "online"]
    conn.executemany("INSERT OR IGNORE INTO iocs VALUES (?,?,?,?,?,?,?)",
                     [("Feodo Tracker", "", "Botnet C2 servers online", "ip:port",
                       defang(f"{r['ip_address']}", "ip") + f":{r.get('port')}", r.get("malware"), now.isoformat())
                      for r in online])
    return f"Feodo Tracker: {len(online)} botnet C2 servers online"


def threatfox(conn, now: datetime) -> str:
    key = os.environ.get("ABUSECH_AUTH_KEY")
    if not key:
        return "ThreatFox: skipped (no ABUSECH_AUTH_KEY secret; optional, see docs/cyber.md)"
    r = requests.post(THREATFOX_API, json={"query": "get_iocs", "days": 1},
                      headers={"Auth-Key": key, "User-Agent": USER_AGENT}, timeout=60)
    data = r.json() if r.ok else {}
    if data.get("query_status") != "ok":
        return f"ThreatFox: no data (HTTP {r.status_code}, {data.get('query_status')})"
    kinds = {"ip:port": "ip:port", "domain": "domain", "url": "url",
             "sha256_hash": "sha256", "md5_hash": "md5", "sha1_hash": "sha1"}
    rows = []
    for i in data.get("data", []):
        kind = kinds.get(i.get("ioc_type"))
        if not kind:
            continue
        value = i["ioc"]
        if kind == "ip:port":
            ip, _, port = value.rpartition(":")
            value = defang(ip, "ip") + f":{port}"
        else:
            value = defang(value, kind)
        rows.append(("ThreatFox", "", f"{i.get('threat_type_desc') or i.get('threat_type') or ''}", kind,
                     value, i.get("malware_printable"), now.isoformat()))
    conn.executemany("INSERT OR IGNORE INTO iocs VALUES (?,?,?,?,?,?,?)", rows)
    return f"ThreatFox: {len(rows)} IOCs from the last 24 hours"


def run():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    conn = store.connect()
    for step in (update_kev, lambda c: research_iocs(c, now), lambda c: feodo(c, now), lambda c: threatfox(c, now)):
        try:
            print(step(conn))
        except Exception as ex:      # one source failing must not stop the others
            print(f"  a source failed: {short_error(ex)}")
        conn.commit()
    cutoff = (now - timedelta(days=store.KEEP_DAYS)).isoformat()
    conn.execute("DELETE FROM iocs WHERE first_seen < ?", (cutoff,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    run()
