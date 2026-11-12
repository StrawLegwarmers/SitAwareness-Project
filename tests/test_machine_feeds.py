import json
import sqlite3

import machine_feeds as mf
import store


def test_csv_cells_cannot_become_formulas():
    assert mf.cell('=HYPERLINK("http://x")') == "'=HYPERLINK(\"http://x\")"
    assert [mf.cell(v) for v in ("+1", "-1", "@SUM(A1)", "plain", None)] == ["'+1", "'-1", "'@SUM(A1)", "plain", ""]


def test_rss_report_html_keeps_only_our_links():
    html = mf.md_to_html('[Reuters](https://r.example/a) reported <script>alert(1)</script> [x](javascript:alert(2))')
    assert '<a href="https://r.example/a">Reuters</a>' in html and "<script>" not in html and 'href="javascript' not in html


def test_stix_patterns_are_escaped(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    conn.execute("INSERT INTO iocs VALUES (?,?,?,?,?,?,?)",
                 ("Vendor", "https://v.example/r", "Report", "domain", "evil[.]example\\'x", "Mal", "2026-11-12T08:00:00+00:00"))
    monkeypatch.setattr(mf, "OUT", tmp_path)
    monkeypatch.setattr(mf, "latest_day", lambda site: None)
    mf.stix_bundle(conn, 3650, ["domain"])
    bundle = json.loads((tmp_path / "cyber-stix.json").read_text())
    ind = next(o for o in bundle["objects"] if o["type"] == "indicator")
    assert ind["pattern"] == "[domain-name:value = 'evil.example\\\\\\'x']"
    assert all(o.get("id") for o in bundle["objects"])
