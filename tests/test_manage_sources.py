import shutil

import manage_sources as ms

BODY = """### Name

Balkan Insight

### Feed or website address

https://balkaninsight.com/feed/

### Region (geopolitical) or section (cyber)

Europe

### Type (geopolitical only)

regional

### Language code

_No response_
"""


def test_issue_forms_are_parsed():
    f = ms.parse_issue(BODY)
    assert f["name"] == "Balkan Insight" and f["language code"] == "" and f["region (geopolitical) or section (cyber)"] == "Europe"


def test_bad_requests_are_refused_before_any_download(monkeypatch):
    monkeypatch.setattr(ms, "check_feed", lambda url: (_ for _ in ()).throw(AssertionError("no download expected")))
    assert ms.add("Europe", "X", "javascript:alert(1)").startswith("Not done")
    assert ms.add("Europe", "Bad Name", "https://e.com/feed").startswith("Not done")
    assert ms.add("Mars", "X", "https://e.com/feed").startswith("Not done")
    assert ms.add("Europe", "X", "https://e.com/feed", lang="english").startswith("Not done")


def test_add_writes_a_quoted_line_and_validates(tmp_path, monkeypatch):
    target = tmp_path / "sources.yaml"
    shutil.copy(ms.sources_path("geo"), target)
    monkeypatch.setattr(ms, "sources_path", lambda site: target if site == "geo" else ms.CONFIG / site / "sources.yaml")
    monkeypatch.setattr(ms, "validate", lambda site: [])
    monkeypatch.setattr(ms, "check_feed", lambda url: {"ok": True, "items": 5, "newest": "2026-11-12", "error": None})
    out = ms.add("Europe", 'Odd "Name": {x}', "https://e.com/feed", note="hello")
    assert out.startswith("Done"), out
    line = target.read_text().rstrip().splitlines()[-1]
    assert 'name: "Odd \\"Name\\": {x}"' in line and "region: europe" in line
