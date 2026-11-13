"""The Markets site: config, official data parsing (fail closed), SEC filings, calendar, export, guardrails."""
import json
from datetime import date, datetime, timezone

import pytest
import requests

import export
import guardrails
import markets_data as md
from config import ROOT, load_site, sites
from narratives import TOPICS


def test_markets_is_a_site_with_valid_pages_and_topics():
    assert "markets" in sites()
    cfg = load_site("markets")
    pages = export.pages_for(cfg)
    shown = {b for p in pages for b in p["show"]}
    assert {"rates", "calendar", "filings", "geolinks", "disclaimer"} <= shown
    assert set(cfg["topics"]) <= set(TOPICS) and "markets" in cfg["topics"]
    assert cfg["ai"]["max_calls"] <= 3


def test_ics_parser_handles_folding_utc_local_and_whole_days():
    text = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Gross Domestic Product\\, 3rd Quarter (Advance Estima\r\n te)\r\n"
            "DTSTART;VALUE=DATE-TIME:20270128T133000Z\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nSUMMARY:Consumer Price Index\r\nDTSTART;TZID=America/New_York:20261210T083000\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nSUMMARY:Holiday\r\nDTSTART;VALUE=DATE:20261225\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    ev = md.ics_events(text)
    assert [e["summary"] for e in ev] == ["Gross Domestic Product, 3rd Quarter (Advance Estimate)", "Consumer Price Index", "Holiday"]
    assert md.to_eastern(ev[0]) == ("2027-01-28", "08:30 ET")            # 13:30 UTC in winter
    assert md.to_eastern(ev[1]) == ("2026-12-10", "08:30 ET")
    assert md.to_eastern(ev[2]) == ("2026-12-25", None)


ATOM = """<feed><entry>
<title>8-K - EXAMPLE CORP (0000000001) (Filer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1/0001-26-1-index.htm"/>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-11-12 &lt;b&gt;AccNo:&lt;/b&gt; 0001-26-1
&lt;br&gt;Item 1.05: Material Cybersecurity Incidents
&lt;br&gt;Item 9.01: Financial Statements and Exhibits</summary>
<updated>2026-11-12T17:30:24-05:00</updated><id>urn:tag:sec.gov,2008:accession-number=0001-26-1</id></entry>
<entry><title>8-K - EXAMPLE CORP (0000000001) (Subject)</title><summary type="html">&lt;br&gt;Item 1.05: x</summary>
<updated>2026-11-12T17:30:24-05:00</updated><id>urn:tag:sec.gov,2008:accession-number=0001-26-1</id></entry>
<entry><title>8-K - PRIVATE FUND LP (0000000002) (Filer)</title><summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-11-12
&lt;br&gt;Item 2.02: Results</summary><updated>2026-11-12T16:00:00-05:00</updated>
<id>urn:tag:sec.gov,2008:accession-number=0002-26-2</id></entry></feed>"""


class Resp:
    def __init__(self, text="", data=None):
        self.text, self._data = text, data

    def json(self):
        return self._data


def test_edgar_entries_are_parsed_and_only_listed_filers_kept(monkeypatch):
    entries = md.parse_edgar(ATOM)
    assert len(entries) == 2 and entries[0]["items"] == ["1.05", "9.01"] and entries[0]["filed"] == "2026-11-12"
    sent = []

    def fake_get(url, contact_email=None, **kw):
        sent.append(contact_email)
        if url.endswith("company_tickers.json"):
            return Resp(data={"0": {"cik_str": 1, "ticker": "EXMP", "title": "Example Corp"}})
        return Resp(ATOM if "start=0&" in url else "<feed></feed>")
    monkeypatch.setattr(md, "get", fake_get)
    out = md.filings("analyst@example.org", now=datetime(2026, 11, 13, 6, tzinfo=timezone.utc))
    assert out["read"] == 2 and out["listed"] == 1
    assert [g["item"] for g in out["groups"]] == ["1.05"] and out["groups"][0]["filings"][0]["ticker"] == "EXMP"
    assert set(sent) == {"analyst@example.org"}                       # the contact goes to the SEC request only...
    assert "analyst@example.org" not in json.dumps(out)              # ...and never into the data
    assert md.filings(None) == {"configured": False}


def test_a_failed_source_is_shown_as_not_available_never_as_a_number(monkeypatch):
    def boom(url, contact_email=None, **kw):
        r = requests.Response()
        r.status_code = 403
        raise requests.HTTPError(response=r)
    monkeypatch.setattr(md, "get", boom)
    rows = md.rates()
    assert rows and all(r["value"] is None and r["error"] == "HTTP 403" for r in rows)
    bad = md.row("US Treasury yields", "10-year", "%", [("2026-11-12", 512.0)], "US Treasury", "https://x")
    assert bad["value"] is None and "out of range" in bad["error"]
    ok = md.row("Energy spot prices", "Brent", "$/barrel", [("2026-11-11", 92.14), ("2026-11-10", 90.16)], "EIA", "https://x")
    assert ok["value"] == 92.14 and ok["change"] == pytest.approx(1.98) and ok["previous_date"] == "2026-11-10" and "stale" in ok


def test_calendar_has_central_banks_and_says_what_it_could_not_read(monkeypatch):
    def boom(url, contact_email=None, **kw):
        raise requests.ConnectionError()
    monkeypatch.setattr(md, "get", boom)
    cal = md.calendar(date(2026, 12, 14), None)
    banks = {e["source"] for e in cal["events"] if e["kind"] == "central bank"}
    assert {"European Central Bank", "Bank of England (MPC)", "Bank of Japan"} <= banks
    assert any(p.startswith("BLS: needs") for p in cal["problems"]) and any(p.startswith("BEA") for p in cal["problems"])
    assert cal["central_banks_until"] >= "2027-10-01"


def test_the_contact_must_look_like_an_email(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "not an email")
    assert md.contact() is None
    monkeypatch.setenv("SEC_CONTACT_EMAIL", " analyst@example.org ")
    assert md.contact() == "analyst@example.org"


def test_geo_links_pick_market_topics_from_the_geopolitical_brief(tmp_path, monkeypatch):
    (tmp_path / "geo").mkdir()
    stories = [{"id": "a", "title": "Iran says tanker hit mine in Hormuz", "status": "updated", "outlets_period": 9, "region": "mena", "articles": []},
               {"id": "b", "title": "Pope visits Peru", "status": "new", "outlets_period": 20, "region": "latam", "articles": []},
               {"id": "c", "title": "EU agrees new sanctions package", "status": "unchanged", "outlets_period": 5, "region": "europe", "articles": []}]
    (tmp_path / "geo" / "2026-11-13.json").write_text(json.dumps({"stories": stories}))
    monkeypatch.setattr(export, "DATA", tmp_path)
    out = export.geo_links(load_site("markets"), "2026-11-13")
    assert [s["id"] for s in out] == ["a"] and "hormuz" in out[0]["terms"]


def test_without_market_data_the_blocks_say_so(monkeypatch, tmp_path):
    monkeypatch.setattr(export, "MARKET_DATA", tmp_path / "missing.json")
    m = export.markets_extras(load_site("markets"), "2026-11-13")
    assert m["rates"] == [] and m["filings"] == {"configured": False}
    assert export.sec_incidents() == {"configured": False, "error": None, "filings": []}


def test_market_judgments_need_the_source_to_have_used_them():
    art = [{"title": "Nvidia shares fall 3% after CEO resigns", "summary": "", "lang": "en"}]
    for bad in ("[1] reported that Nvidia shares soared.", "[1] reported a bullish outlook for Nvidia shares."):
        ok, why = guardrails.check(bad, art)
        assert not ok, bad
    assert guardrails.check("[1] reported that Nvidia shares fell 3% after the CEO resigned.", art)[0]


def test_the_contact_secret_is_only_given_to_the_market_data_step():
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert wf.count("secrets.SEC_CONTACT_EMAIL") == 1
    step = wf.split("Market data (rates, calendar, SEC filings)")[1].split("- name:")[0]
    assert "secrets.SEC_CONTACT_EMAIL" in step


def test_the_website_knows_the_markets_site_and_blocks():
    js = (ROOT / "site" / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'const SITES = ["geo", "cyber", "markets"]' in js
    for block in ("disclaimer()", "rates(day)", "calendar(day)", "filings(day)", "geolinks(day)", "secincidents(day)"):
        assert block in js
