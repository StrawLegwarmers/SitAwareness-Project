from datetime import datetime, timezone

import normalize


def test_canonical_url_drops_tracking_and_fragment():
    a = normalize.canonical_url("http://WWW.DW.com/en/story/a-123/?maca=en-rss&utm_source=x&id=7#top")
    assert a == "https://www.dw.com/en/story/a-123?id=7"


def test_clean_text_strips_html_and_cuts_at_word():
    assert normalize.clean_text("<p>Hello &amp; <b>world</b></p>") == "Hello & world"
    long = "word " * 200
    out = normalize.clean_text(long, limit=50)
    assert len(out) <= 51 and out.endswith("…")


def entry(**kw):
    e = {"title": "Talks resume in Geneva", "link": "https://example.com/a", "summary": "Text",
         "published_parsed": (2026, 11, 12, 8, 0, 0, 0, 0, 0)}
    e.update(kw)
    return e


SOURCE = {"name": "Example News", "site": "geo", "region": "europe", "type": "regional", "lang": "en"}
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def test_only_web_links_are_accepted():
    assert normalize.normalize_entry(entry(link="javascript:alert(1)"), SOURCE, "example.com", NOW) is None
    assert normalize.normalize_entry(entry(link="data:text/html,x"), SOURCE, "example.com", NOW) is None
    assert normalize.normalize_entry(entry(title=""), SOURCE, "example.com", NOW) is None
    assert normalize.normalize_entry(entry(), SOURCE, "example.com", NOW)["url"] == "https://example.com/a"


def test_future_dates_are_clamped_and_missing_dates_use_now():
    a = normalize.normalize_entry(entry(published_parsed=(2027, 1, 1, 0, 0, 0, 0, 0, 0)), SOURCE, "example.com", NOW)
    assert a["published"] == NOW.isoformat()
    b = normalize.normalize_entry(entry(published_parsed=None), SOURCE, "example.com", NOW)
    assert b["published"] == NOW.isoformat()


def test_google_news_items_are_unwrapped():
    e = entry(title="Ceasefire talks resume - Reuters", source={"title": "Reuters"})
    a = normalize.normalize_entry(e, SOURCE, "news.google.com", NOW)
    assert a["outlet"] == "Reuters" and a["title"] == "Ceasefire talks resume" and a["summary"] == ""


def test_same_url_same_id_and_kind_label():
    a = normalize.normalize_entry(entry(link="https://example.com/opinion/a?utm_source=rss"), SOURCE, "example.com", NOW)
    b = normalize.normalize_entry(entry(link="https://example.com/opinion/a"), SOURCE, "example.com", NOW)
    assert a["id"] == b["id"]
    assert a["kind"] == "opinion"
