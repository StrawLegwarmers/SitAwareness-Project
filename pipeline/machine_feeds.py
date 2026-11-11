"""
machine_feeds.py - feeds for other tools, such as OpenCTI.

Usage:
  python pipeline/machine_feeds.py      # (export.py also runs this at the end)

Writes site/feeds/ (settings in config/feeds.yaml):
  geo.xml, cyber.xml     RSS 2.0: one item per story per day with new reporting
  iocs.csv               indicators, REFANGED so tools get real values
  vulnerabilities.csv    CISA KEV additions and CVEs in the news
  cyber-stix.json        the same indicators and vulnerabilities as a STIX 2.1 bundle
  index.json             what's here and when it was built (read by the website's OpenCTI page)

This is a PULL design: the files sit on the public website and your tool fetches them on its
own schedule. The website never connects to anything and holds no keys.
Everything comes from data that already exists: the day's JSON (stories, reports that passed
the guardrails, original headlines) and the database (IOCs, KEV). No AI, no new text.
"""
from __future__ import annotations

import csv
import html
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import store
from config import CONFIG, ROOT, load_yaml, sites
from indicators import plain

DATA = ROOT / "site" / "data"
OUT = ROOT / "site" / "feeds"
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
NOTE = ("Collected automatically from public RSS feeds. Each sentence restates what one outlet reported "
        "and passed automated checks against that outlet's headline and summary. Verify at source.")


def settings() -> dict:
    path = CONFIG / "feeds.yaml"
    return load_yaml(path) if path.exists() else {}


def site_url() -> str:
    """The website's address, so feed items can link back. SITE_URL wins; on GitHub it's worked out."""
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"].rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")          # "owner/name", set by GitHub Actions
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def latest_day(site: str) -> dict | None:
    files = sorted((DATA / site).glob("20*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def md_to_html(text: str) -> str:
    """Report text: escape everything, then turn only our own [Outlet](https://...) links into <a>."""
    out, last = [], 0
    for m in LINK.finditer(text):
        out.append(html.escape(text[last:m.start()]))
        out.append(f'<a href="{html.escape(m.group(2))}">{html.escape(m.group(1))}</a>')
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def page_for(day: dict, story: dict) -> str:
    """Which website page shows this story (the region page on geo, the first page otherwise)."""
    region = story.get("region") or story.get("group")
    for p in day.get("pages") or []:
        if f"group:{region}" in p["show"]:
            return p["id"]
    return (day.get("pages") or [{"id": ""}])[0]["id"]


def rss(site: str, days: int) -> int:
    day = latest_day(site)
    if not day:
        return 0
    base, today = site_url(), day["date"]
    since = (datetime.fromisoformat(today) - timedelta(days=days - 1)).date().isoformat()
    names = {g["id"]: g["name"] for g in day["groups"]}
    countries = day.get("countries") or {}
    items = []
    for s in day["stories"]:
        for d in sorted({r["date"] for r in s["reports"]} | {a.get("added") for a in s["articles"] if a.get("added")}, reverse=True):
            if not d or d < since:
                continue
            reps = [r for r in s["reports"] if r["date"] == d]
            arts = [a for a in s["articles"] if a.get("added") == d]
            if not reps and not arts:
                continue
            where = [names.get(s.get("region") or s["group"], "")] + [countries.get(c, {}).get("name", c) for c in s.get("countries", [])]
            body = f"<p><b>{html.escape(' · '.join(w for w in where if w))}</b></p>"
            if reps:
                body += f"<p><b>Reported on {d}:</b></p><ul>" + "".join(f"<li>{md_to_html(r['text'])}</li>" for r in reps) + "</ul>"
            if arts:
                body += "<p><b>Original headlines:</b></p><ul>" + "".join(
                    f'<li><a href="{html.escape(a["url"])}">{html.escape(a["title"])}</a> ({html.escape(a["outlet"])})</li>' for a in arts) + "</ul>"
            body += f"<p><i>{html.escape(NOTE)}</i></p>"
            link = f"{base}#/{site}/{d}/{page_for(day, s)}" if base else (arts or s["articles"] or [{"url": ""}])[0]["url"]
            when = datetime.fromisoformat(day["generated"]) if d == today else datetime.fromisoformat(d + "T12:00:00+00:00")
            cats = [w for w in where if w] + (["single source"] if s.get("single_source") and d == today else [])
            items.append((when, f"""  <item>
    <title>{html.escape(s['title'])}</title>
    <link>{html.escape(link)}</link>
    <guid isPermaLink="false">sitaware:{site}:{html.escape(s['id'])}:{d}</guid>
    <pubDate>{format_datetime(when)}</pubDate>
{''.join(f'    <category>{html.escape(c)}</category>{chr(10)}' for c in cats)}    <description>{html.escape(body)}</description>
  </item>"""))
    items.sort(key=lambda x: x[0], reverse=True)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Situational Awareness Project: {html.escape(day['name'])}</title>
  <link>{html.escape(base or 'https://github.com/')}</link>
  <description>Stories with new reporting, one item per story per day. Attributed reports and original headlines only. {html.escape(NOTE)}</description>
  <lastBuildDate>{format_datetime(datetime.fromisoformat(day['generated']))}</lastBuildDate>
{chr(10).join(x[1] for x in items)}
</channel>
</rss>
"""
    (OUT / f"{site}.xml").write_text(xml, encoding="utf-8")
    return len(items)


# STIX / OpenCTI names for each kind of indicator (used by the CSV mapper's "dynamic mapping")
OPENCTI_TYPE = {"sha256": "StixFile", "sha1": "StixFile", "md5": "StixFile", "ip": "IPv4-Addr",
                "ip:port": "IPv4-Addr", "domain": "Domain-Name", "url": "Url"}
HASH_NAME = {"sha256": "SHA-256", "sha1": "SHA-1", "md5": "MD5"}


def iocs_csv(conn, days: int, kinds: list[str]) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute("SELECT * FROM iocs WHERE first_seen >= ? ORDER BY first_seen DESC", (since,)).fetchall()
    n = 0
    with (OUT / "iocs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["opencti_type", "value", "hash_algorithm", "port", "kind", "first_seen",
                    "source", "report_title", "report_url", "malware"])
        for r in rows:
            if r["type"] not in kinds:
                continue
            value, port = plain(r["value"]), ""
            if r["type"] == "ip:port":
                value, _, port = value.rpartition(":")
            w.writerow([OPENCTI_TYPE.get(r["type"], r["type"]), value, HASH_NAME.get(r["type"], ""), port, r["type"],
                        r["first_seen"], r["source"], r["report_title"], r["report_url"], r["malware"] or ""])
            n += 1
    return n


def vulnerabilities_csv(conn, days: int) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    kev = [dict(r) for r in conn.execute("SELECT * FROM kev WHERE date_added >= ? ORDER BY date_added DESC", (since,))]
    day = latest_day("cyber") or {}
    news = (day.get("vulns") or {}).get("in_news", [])
    with (OUT / "vulnerabilities.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cve", "why_listed", "vendor", "product", "name", "description", "kev_date_added",
                    "kev_due_date", "known_ransomware_use", "outlets_in_news", "example_article"])
        seen = set()
        for k in kev:
            mention = next((c for c in news if c["cve"] == k["cve"]), None)
            w.writerow([k["cve"], "CISA KEV" + (" + news" if mention else ""), k["vendor"], k["product"], k["name"],
                        k["description"], k["date_added"], k["due_date"], k["ransomware"],
                        mention["outlets"] if mention else 0, mention["articles"][0]["url"] if mention else ""])
            seen.add(k["cve"])
        for c in news:
            if c["cve"] in seen:
                continue
            kv = c.get("kev") or {}
            w.writerow([c["cve"], "news" + (" (in KEV)" if kv else ""), kv.get("vendor", ""), kv.get("product", ""),
                        kv.get("name", ""), kv.get("description", ""), kv.get("date_added", ""), kv.get("due_date", ""),
                        kv.get("ransomware", ""), c["outlets"], c["articles"][0]["url"] if c["articles"] else ""])
            seen.add(c["cve"])
    return len(seen)


# ── STIX 2.1 ──────────────────────────────────────────────────────────────
# STIX is the standard format for sharing threat intelligence. A "bundle" is a list of objects:
#   identity        who produced this (the project)                  marking-definition  TLP
#   indicator       a pattern that detects something malicious        malware             a family name
#   relationship    "this indicator indicates that malware"           vulnerability       a CVE
#   report          one vendor research report and the indicators it listed
# Ids are made from the content (uuid5), so the same indicator always gets the same id and a
# platform like OpenCTI updates it instead of creating a duplicate every day.
NS = uuid.UUID("5f0a6c2e-8d4b-4f3a-9e1c-7b2d3a4c5e6f")                 # this project's own namespace
TLP_CLEAR = "marking-definition--613f2e26-407d-48c7-9eca-b8e91df99dc9"   # the standard TLP:WHITE (= CLEAR) id
PATTERNS = {"sha256": "[file:hashes.'SHA-256' = '{}']", "sha1": "[file:hashes.'SHA-1' = '{}']",
            "md5": "[file:hashes.MD5 = '{}']", "ip": "[ipv4-addr:value = '{}']", "ip:port": "[ipv4-addr:value = '{}']",
            "domain": "[domain-name:value = '{}']", "url": "[url:value = '{}']"}


def sid(kind: str, *parts) -> str:
    return f"{kind}--{uuid.uuid5(NS, '|'.join(str(p) for p in parts))}"


def stamp(iso: str) -> str:
    """'2026-11-11T10:29:04+00:00' -> '2026-11-11T10:29:04.000Z' (the form STIX wants)."""
    d = datetime.fromisoformat(iso if "T" in iso else iso + "T00:00:00+00:00").astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def stix_bundle(conn, days: int, kinds: list[str]) -> int:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    me = sid("identity", "situational-awareness-project")
    base = {"spec_version": "2.1", "created_by_ref": me, "object_marking_refs": [TLP_CLEAR]}
    objects = [
        {"type": "marking-definition", "spec_version": "2.1", "id": TLP_CLEAR, "created": "2017-01-20T00:00:00.000Z",
         "definition_type": "tlp", "name": "TLP:WHITE", "definition": {"tlp": "white"}},
        {"type": "identity", "spec_version": "2.1", "id": me, "created": "2026-01-01T00:00:00.000Z",
         "modified": "2026-01-01T00:00:00.000Z", "name": "Situational Awareness Project", "identity_class": "organization",
         "description": "Open-source collection feed built from public RSS sources and vendor research. Verify at source."},
    ]
    malware, reports = {}, {}
    for r in conn.execute("SELECT * FROM iocs WHERE first_seen >= ? ORDER BY first_seen", (since,)):
        if r["type"] not in kinds:
            continue
        value = plain(r["value"])
        if r["type"] == "ip:port":
            value = value.rpartition(":")[0]
        when = stamp(r["first_seen"])
        ind = {"type": "indicator", "id": sid("indicator", r["type"], value), "created": when, "modified": when,
               "name": value, "pattern": PATTERNS[r["type"]].format(value.replace("\\", "\\\\").replace("'", "\\'")),
               "pattern_type": "stix", "valid_from": when, "indicator_types": ["malicious-activity"], "confidence": 50,
               "description": f"Listed in: {r['report_title']} ({r['source']})" if r["report_url"] else f"{r['source']}: {r['report_title']}",
               "x_opencti_main_observable_type": OPENCTI_TYPE[r["type"]], **base}
        if r["report_url"]:
            ind["external_references"] = [{"source_name": r["source"], "url": r["report_url"], "description": r["report_title"]}]
            rep = reports.setdefault(r["report_url"], {"title": r["report_title"], "source": r["source"], "when": when, "refs": []})
            rep["refs"].append(ind["id"])
        objects.append(ind)
        if r["malware"]:
            m = malware.setdefault(r["malware"], {"type": "malware", "id": sid("malware", r["malware"].lower()), "created": when,
                                                   "modified": when, "name": r["malware"], "is_family": True, **base})
            objects.append({"type": "relationship", "id": sid("relationship", ind["id"], m["id"]), "created": when, "modified": when,
                            "relationship_type": "indicates", "source_ref": ind["id"], "target_ref": m["id"], **base})
    objects += malware.values()
    for url, rep in reports.items():
        objects.append({"type": "report", "id": sid("report", url), "created": rep["when"], "modified": rep["when"],
                        "name": rep["title"], "published": rep["when"], "report_types": ["threat-report"],
                        "description": f"Indicators published by {rep['source']} in this report, collected automatically. Verify at source.",
                        "object_refs": rep["refs"], "external_references": [{"source_name": rep["source"], "url": url}], **base})
    # Vulnerabilities: added to CISA KEV in the period, and CVEs in the news
    kev = {r["cve"]: dict(r) for r in conn.execute("SELECT * FROM kev WHERE date_added >= ?", (since[:10],))}
    news = {c["cve"]: c for c in ((latest_day("cyber") or {}).get("vulns") or {}).get("in_news", [])}
    for cve in sorted(set(kev) | set(news)):
        k, n = kev.get(cve) or (news.get(cve) or {}).get("kev") or {}, news.get(cve) or {}
        when = stamp(k.get("date_added") or now.isoformat())
        refs = [{"source_name": "cve", "external_id": cve}]
        refs += [{"source_name": a["outlet"], "url": a["url"], "description": a["title"]} for a in n.get("articles", [])[:3]]
        vuln = {"type": "vulnerability", "id": sid("vulnerability", cve), "created": when, "modified": when, "name": cve,
                "description": k.get("description") or f"Mentioned by {n.get('outlets', 0)} outlet(s) in the news.",
                "external_references": refs, **base}
        if k:
            vuln["labels"] = ["cisa-kev"]
            vuln["x_opencti_cisa_kev"] = True
        objects.append(vuln)
    bundle = {"type": "bundle", "id": sid("bundle", now.date().isoformat()), "objects": objects}
    (OUT / "cyber-stix.json").write_text(json.dumps(bundle, indent=1, ensure_ascii=False), encoding="utf-8")
    return len(objects)


def run() -> str:
    cfg = settings()
    if not cfg:
        return "Machine feeds: off (no config/feeds.yaml)"
    OUT.mkdir(parents=True, exist_ok=True)
    done = []
    if cfg.get("rss", True):
        for site in sites():
            done.append(f"{site}.xml {rss(site, int(cfg.get('rss_days', 3)))} items")
    conn = store.connect()
    if cfg.get("iocs_csv", True):
        done.append(f"iocs.csv {iocs_csv(conn, int(cfg.get('ioc_days', 3)), cfg.get('ioc_types') or list(OPENCTI_TYPE))} indicators")
    if cfg.get("vulnerabilities_csv", True):
        done.append(f"vulnerabilities.csv {vulnerabilities_csv(conn, int(cfg.get('ioc_days', 3)))} CVEs")
    if cfg.get("stix", True):
        done.append(f"cyber-stix.json {stix_bundle(conn, int(cfg.get('ioc_days', 3)), cfg.get('ioc_types') or list(OPENCTI_TYPE))} STIX objects")
    conn.close()
    # A small table of contents, read by the website's OpenCTI page
    (OUT / "index.json").write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": {p.name: {"bytes": p.stat().st_size, "summary": next((d for d in done if d.startswith(p.name)), "")}
                  for p in sorted(OUT.iterdir()) if p.name != "index.json"},
        "ioc_types": cfg.get("ioc_types") or list(OPENCTI_TYPE), "days": int(cfg.get("ioc_days", 3)),
    }, indent=1), encoding="utf-8")
    return "Wrote site/feeds/: " + ", ".join(done)


if __name__ == "__main__":
    print(run())
