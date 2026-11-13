"""
markets_data.py - official numbers and dates for the Markets site. Code only, no AI.

Usage:
  python pipeline/markets_data.py           # fetch everything, write data/markets-data.json
  python pipeline/markets_data.py --show    # also print what was fetched

What it collects. Each part stands alone: one failing source never stops the others, and a value
that couldn't be fetched is shown as "not available", never as zero or as yesterday's number.

  rates     US Treasury par yields (US Treasury), SOFR and EFFR (New York Fed), the euro short-term
            rate and euro reference exchange rates (ECB), WTI, Brent and Henry Hub spot prices (EIA).
            Each with the date it applies to, the previous value, and a link to the source. All
            public-domain or freely published official data. No stock index levels: those are
            licensed (S&P, Dow Jones), so they are left out.
  calendar  the next 7 days: central bank decisions (config/markets/calendar.yaml, from the banks'
            own schedules), US statistical releases (the BLS and BEA calendars) and Treasury auctions.
            No forecasts or "consensus" numbers: those are licensed and they are predictions.
  filings   8-K filings by listed US companies in the last day, by item (results, deals, executive
            changes, cybersecurity incidents...), from the SEC's EDGAR system.

THE CONTACT EMAIL. The SEC asks every automated request to say who is asking, with an email
address (https://www.sec.gov/os/webmaster-faq#developers), and BLS refuses requests that don't.
Set it as the repository secret SEC_CONTACT_EMAIL. It is only ever sent to sec.gov and bls.gov,
in the request header; it is never written to the repository, the website or the logs. Without
it, filings and the BLS calendar are skipped and the website says so.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from html import unescape

import requests

from config import CONFIG, ROOT, load_yaml

OUT = ROOT / "data" / "markets-data.json"
UA = "SitAwareness-Project/1.0 (+https://github.com/StrawLegwarmers/SitAwareness-Project)"
TIMEOUT = 30
STALE_DAYS = 7          # a value older than this is flagged as stale
CALENDAR_DAYS = 7
FILINGS_HOURS = 26      # 8-Ks filed in the last day (a little more, so a late run misses nothing)
FILINGS_PAGES = 12      # at most 1,200 filings read per run; the SEC allows 10 requests a second
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def contact() -> str | None:
    """The contact email from the SEC_CONTACT_EMAIL secret, if it looks like an email address."""
    value = (os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
    return value if EMAIL_RE.match(value) else None


def get(url: str, contact_email: str | None = None, **kw) -> requests.Response:
    ua = f"SitAwareness-Project {contact_email}" if contact_email else UA
    r = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def why(ex: Exception) -> str:
    """A short reason for the website. Never includes headers, so never the contact email."""
    if isinstance(ex, requests.HTTPError) and ex.response is not None:
        return f"HTTP {ex.response.status_code}"
    return type(ex).__name__


# ── Rates and prices ──────────────────────────────────────────────────────────

# (group, name, unit, value range that makes sense: anything outside is treated as a bad read)
TREASURY = [("3 Mo", "3-month"), ("2 Yr", "2-year"), ("10 Yr", "10-year"), ("30 Yr", "30-year")]
TREASURY_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"
ECB_FX = [("USD", "EUR/USD"), ("GBP", "EUR/GBP"), ("JPY", "EUR/JPY"), ("CHF", "EUR/CHF"), ("CNY", "EUR/CNY")]
ECB_FX_URL = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
EIA = [("RWTC", "pet", "WTI crude (Cushing)", "$/barrel"), ("RBRTE", "pet", "Brent crude", "$/barrel"),
       ("RNGWHHD", "ng", "Henry Hub natural gas", "$/MMBtu")]
RANGES = {"%": (-5, 30), "$/barrel": (1, 500), "$/MMBtu": (0.1, 100), "fx": (0.0001, 100000)}


def row(group, name, unit, obs, source, url, error=None) -> dict:
    """One table row from [(date, value), ...] newest first. Checks the value makes sense."""
    out = {"group": group, "name": name, "unit": unit, "source": source, "url": url}
    obs = [(d, v) for d, v in obs if v is not None]
    if error or not obs:
        return out | {"value": None, "error": error or "no data"}
    lo, hi = RANGES.get(unit if unit in RANGES else "fx")
    if not lo <= obs[0][1] <= hi:
        return out | {"value": None, "error": f"value out of range ({obs[0][1]})"}
    out |= {"value": obs[0][1], "date": obs[0][0]}
    if len(obs) > 1:
        out |= {"previous": obs[1][1], "previous_date": obs[1][0], "change": round(obs[0][1] - obs[1][1], 4)}
    out["stale"] = (date.today() - date.fromisoformat(obs[0][0])).days > STALE_DAYS
    return out


def treasury_rows() -> list[dict]:
    group, src = "US Treasury yields", "US Treasury"
    try:
        rows = []
        for year in (date.today().year, date.today().year - 1):
            url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                   f"{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
            rows += list(csv.DictReader(io.StringIO(get(url).text)))
            if len(rows) >= 2:
                break
        def iso(d):                                    # "11/12/2026" -> "2026-11-12"
            m, dd, y = d.split("/")
            return f"{y}-{int(m):02d}-{int(dd):02d}"
        rows.sort(key=lambda r: iso(r["Date"]), reverse=True)
        return [row(group, name, "%", [(iso(r["Date"]), float(r[col])) for r in rows[:2] if r.get(col)], src, TREASURY_URL)
                for col, name in TREASURY]
    except Exception as ex:                            # one source failing must not stop the rest
        return [row(group, name, "%", [], src, TREASURY_URL, why(ex)) for _, name in TREASURY]


def nyfed_rows() -> list[dict]:
    out = []
    for path, name, url in (("secured/sofr", "SOFR", "https://www.newyorkfed.org/markets/reference-rates/sofr"),
                            ("unsecured/effr", "Effective fed funds rate (EFFR)", "https://www.newyorkfed.org/markets/reference-rates/effr")):
        try:
            refs = get(f"https://markets.newyorkfed.org/api/rates/{path}/last/2.json").json()["refRates"]
            refs.sort(key=lambda r: r["effectiveDate"], reverse=True)
            out.append(row("US money markets", name, "%", [(r["effectiveDate"], float(r["percentRate"])) for r in refs],
                           "New York Fed", url))
        except Exception as ex:
            out.append(row("US money markets", name, "%", [], "New York Fed", url, why(ex)))
    return out


def ecb_csv(key: str) -> list[dict]:
    url = f"https://data-api.ecb.europa.eu/service/data/{key}?lastNObservations=2&format=csvdata"
    return list(csv.DictReader(io.StringIO(get(url).text)))


def ecb_rows() -> list[dict]:
    out = []
    estr_url = "https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_short-term_rate/html/index.en.html"
    try:
        obs = sorted(((r["TIME_PERIOD"], float(r["OBS_VALUE"])) for r in ecb_csv("EST/B.EU000A2X2A25.WT")), reverse=True)
        out.append(row("Euro area", "Euro short-term rate (€STR)", "%", obs, "ECB", estr_url))
    except Exception as ex:
        out.append(row("Euro area", "Euro short-term rate (€STR)", "%", [], "ECB", estr_url, why(ex)))
    try:
        rows = ecb_csv("EXR/D." + "+".join(c for c, _ in ECB_FX) + ".EUR.SP00.A")
        for cur, name in ECB_FX:
            obs = sorted(((r["TIME_PERIOD"], float(r["OBS_VALUE"])) for r in rows if r["CURRENCY"] == cur), reverse=True)
            out.append(row("ECB euro reference rates", name, cur, obs, "ECB", ECB_FX_URL))
    except Exception as ex:
        out += [row("ECB euro reference rates", name, cur, [], "ECB", ECB_FX_URL, why(ex)) for cur, name in ECB_FX]
    return out


def eia_rows() -> list[dict]:
    import xlrd
    out = []
    for key, area, name, unit in EIA:
        url = f"https://www.eia.gov/dnav/{area}/hist/{key.lower()}D.htm"
        try:
            book = xlrd.open_workbook(file_contents=get(f"https://www.eia.gov/dnav/{area}/hist_xls/{key}d.xls").content)
            sheet = book.sheet_by_name("Data 1")
            obs = []
            for i in range(sheet.nrows - 1, 2, -1):
                d, v = sheet.row_values(i)[:2]
                if isinstance(d, float) and isinstance(v, float):
                    obs.append((xlrd.xldate_as_datetime(d, book.datemode).date().isoformat(), v))
                if len(obs) == 2:
                    break
            out.append(row("Energy spot prices", name, unit, obs, "EIA", url))
        except Exception as ex:
            out.append(row("Energy spot prices", name, unit, [], "EIA", url, why(ex)))
    return out


def rates() -> list[dict]:
    return treasury_rows() + nyfed_rows() + ecb_rows() + eia_rows()


# ── Calendar ──────────────────────────────────────────────────────────────────

def ics_events(text: str) -> list[dict]:
    """VEVENTs of an iCalendar file: [{"start": datetime or date, "summary": str}]. Handles folded lines."""
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    out, ev = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            ev = {}
        elif line == "END:VEVENT" and ev is not None:
            if ev.get("start") and ev.get("summary"):
                out.append(ev)
            ev = None
        elif ev is not None and ":" in line:
            key, value = line.split(":", 1)
            name = key.split(";")[0]
            if name == "SUMMARY":
                ev["summary"] = re.sub(r"\\([,;\\])", r"\1", value).replace("\\n", " ").strip()
            elif name == "DTSTART":
                v = value.strip()
                try:
                    if len(v) == 8:                                    # a whole day: 20261113
                        ev["start"] = datetime.strptime(v, "%Y%m%d").date()
                    elif v.endswith("Z"):
                        ev["start"] = datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                    else:                                              # local time (TZID=America/New_York)
                        ev["start"] = datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
                        ev["tz"] = (re.search(r"TZID=([^;:]+)", key) or [None, None])[1]
                except ValueError:
                    pass
    return out


def to_eastern(ev: dict) -> tuple[str, str | None]:
    """(date, "08:30 ET") for an event. US releases are scheduled in Eastern time."""
    start = ev["start"]
    if isinstance(start, datetime) and start.tzinfo:
        from zoneinfo import ZoneInfo
        local = start.astimezone(ZoneInfo("America/New_York"))
        return local.date().isoformat(), local.strftime("%H:%M ET")
    if isinstance(start, datetime):
        return start.date().isoformat(), start.strftime("%H:%M") + (" ET" if (ev.get("tz") or "").endswith("New_York") else "")
    return start.isoformat(), None


def calendar(today: date, contact_email: str | None) -> dict:
    end = today + timedelta(days=CALENDAR_DAYS)
    events, problems = [], []

    def keep(d: str) -> bool:
        return today.isoformat() <= d <= end.isoformat()

    for bank in (load_yaml(CONFIG / "markets" / "calendar.yaml").get("banks") or []):
        for d in bank.get("dates") or []:
            if keep(str(d)):
                events.append({"date": str(d), "time": None, "title": f"{bank['name']}: policy decision",
                               "kind": "central bank", "source": bank["name"], "url": bank["url"]})
    feeds = [("BEA", "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics", "https://www.bea.gov/news/schedule", None)]
    if contact_email:
        feeds.append(("BLS", "https://www.bls.gov/schedule/news_release/bls.ics", "https://www.bls.gov/schedule/news_release/", contact_email))
    else:
        problems.append("BLS: needs the SEC_CONTACT_EMAIL secret (BLS refuses requests without a contact address)")
    for name, url, page, email in feeds:
        try:
            for ev in ics_events(get(url, email).text):
                d, t = to_eastern(ev)
                if keep(d):
                    events.append({"date": d, "time": t, "title": ev["summary"], "kind": "statistical release",
                                   "source": name, "url": page})
        except Exception as ex:
            problems.append(f"{name}: {why(ex)}")
    try:
        for s in get("https://www.treasurydirect.gov/TA_WS/securities/upcoming?format=json").json():
            d = (s.get("competitiveAuctionCloseDate") or s.get("auctionDate") or "")[:10]
            if d and keep(d):
                amount = s.get("offeringAmount")
                size = f" (${int(amount) / 1e9:,.0f}bn offered)" if str(amount or "").isdigit() else ""
                close = s.get("competitiveAuctionCloseTime")          # TreasuryDirect times are Eastern
                events.append({"date": d, "time": f"{close} ET" if close else None,
                               "title": f"Treasury auction: {s.get('securityDescription') or s.get('securityTerm', '') + ' ' + s.get('securityType', '')}{size}",
                               "kind": "Treasury auction", "source": "TreasuryDirect", "url": "https://www.treasurydirect.gov/auctions/upcoming/"})
    except Exception as ex:
        problems.append(f"TreasuryDirect: {why(ex)}")
    events.sort(key=lambda e: (e["date"], e["time"] or "99", e["title"]))
    last = max((str(d) for b in load_yaml(CONFIG / "markets" / "calendar.yaml").get("banks") or [] for d in b.get("dates") or []), default=None)
    return {"from": today.isoformat(), "to": end.isoformat(), "events": events, "problems": problems,
            "central_banks_until": last}


# ── SEC filings ───────────────────────────────────────────────────────────────

# 8-K items worth an analyst's attention, most unusual first. Others (Regulation FD, "other
# events", exhibits) are counted but not listed.
ITEMS = {
    "1.05": "Cybersecurity incidents",
    "1.03": "Bankruptcy or receivership",
    "3.01": "Delisting notices and listing rule failures",
    "4.02": "Earlier financial statements no longer reliable",
    "5.01": "Changes in control",
    "2.01": "Acquisitions and sales completed",
    "1.01": "Material agreements signed",
    "1.02": "Material agreements ended",
    "2.05": "Exit or restructuring costs",
    "2.06": "Impairments",
    "4.01": "Auditor changes",
    "5.02": "Directors and officers: departures and appointments",
    "2.02": "Results of operations",
}
EDGAR = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include"
         "&start={start}&count=100&output=atom")


def parse_edgar(atom: str) -> list[dict]:
    """Entries of EDGAR's 'latest filings' Atom feed."""
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", atom, re.S):
        title = unescape((re.search(r"<title>(.*?)</title>", e, re.S) or [None, ""])[1])
        m = re.match(r"\s*(8-K(?:/A)?)\s*-\s*(.+?)\s*\((\d{10})\)\s*\((\w+)\)", title)
        if not m or m.group(4) != "Filer":
            continue
        summary = unescape((re.search(r"<summary[^>]*>(.*?)</summary>", e, re.S) or [None, ""])[1])
        out.append({
            "form": m.group(1), "company": m.group(2), "cik": int(m.group(3)),
            "url": (re.search(r'<link[^>]*href="([^"]+)"', e) or [None, ""])[1],
            "updated": (re.search(r"<updated>(.*?)</updated>", e) or [None, ""])[1],
            "filed": (re.search(r"Filed:</b>\s*(\d{4}-\d{2}-\d{2})", summary) or [None, ""])[1],
            "accession": (re.search(r"accession-number=([\d-]+)", e) or [None, ""])[1],
            "items": sorted(set(re.findall(r"Item (\d\.\d\d)", summary))),
        })
    return out


def filings(contact_email: str | None, now: datetime | None = None) -> dict:
    if not contact_email:
        return {"configured": False}
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=FILINGS_HOURS)
    try:
        tickers = {int(v["cik_str"]): v["ticker"] for v in get("https://www.sec.gov/files/company_tickers.json", contact_email).json().values()}
        seen, entries = set(), []
        for page in range(FILINGS_PAGES):
            batch = parse_edgar(get(EDGAR.format(start=page * 100), contact_email).text)
            fresh = [e for e in batch if e["updated"] and datetime.fromisoformat(e["updated"]) >= since]
            for e in fresh:
                if e["accession"] not in seen:
                    seen.add(e["accession"])
                    entries.append(e)
            if len(fresh) < len(batch) or not batch:
                break                                   # reached filings older than the window
            time.sleep(0.2)                             # well under the SEC's 10 requests a second
    except Exception as ex:
        return {"configured": True, "error": why(ex)}
    listed = [e | {"ticker": tickers[e["cik"]]} for e in entries if e["cik"] in tickers]
    groups = []
    for item, label in ITEMS.items():
        hits = [e for e in listed if item in e["items"]]
        if hits:
            groups.append({"item": item, "label": label, "filings": [
                {k: e[k] for k in ("company", "ticker", "form", "filed", "url", "items")} for e in hits]})
    return {"configured": True, "since": since.isoformat(timespec="minutes"), "read": len(entries),
            "listed": len(listed), "groups": groups}


# ── Putting it together ───────────────────────────────────────────────────────

def run(show: bool = False) -> dict:
    email = contact()
    today = datetime.now(timezone.utc).date()
    data = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rates": rates(), "calendar": calendar(today, email), "filings": filings(email)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in data["rates"] if r.get("value") is not None)
    f = data["filings"]
    print(f"Rates: {ok} of {len(data['rates'])} available; calendar: {len(data['calendar']['events'])} events "
          f"in the next {CALENDAR_DAYS} days" + (f" ({'; '.join(data['calendar']['problems'])})" if data["calendar"]["problems"] else "")
          + "; filings: " + ("not configured (set the SEC_CONTACT_EMAIL secret)" if not f.get("configured") else
                             f"failed ({f['error']})" if f.get("error") else
                             f"{f['read']} 8-Ks read, {f['listed']} by listed companies"))
    if show:
        for r in data["rates"]:
            print(f"  {r['group']:<26} {r['name']:<32} {r.get('value')} {r['unit']} ({r.get('date') or r.get('error')})")
        for e in data["calendar"]["events"]:
            print(f"  {e['date']} {e['time'] or '':<9} {e['title']}")
        for g in f.get("groups") or []:
            print(f"  {g['item']} {g['label']}: {len(g['filings'])}")
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Official rates, calendar and SEC filings for the Markets site.")
    ap.add_argument("--show", action="store_true", help="print what was fetched")
    run(ap.parse_args().show)
