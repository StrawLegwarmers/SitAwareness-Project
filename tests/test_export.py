import json

import export


def test_dates_are_written_the_same_everywhere():
    assert export.short_date("2026-11-08T23:30:00+00:00") == "8 Nov 2026"
    assert export.short_date("nonsense") == ""
    assert export.dated("[R](https://r) reported X.", "2026-11-08") == "On 8 Nov 2026, [R](https://r) reported X."
    assert export.dated("According to [R](https://r), X.", "2026-11-08").startswith("On 8 Nov 2026, according to")


def story(**kw):
    s = {"id": "s", "group": "europe", "title": "T", "first_seen": "2026-11-10", "last_updated": "2026-11-12",
         "article_count": 2, "reports": [], "articles": []}
    s.update(kw)
    return s


def test_story_for_site_counts_reach_and_corroboration():
    arts = [{"id": "a", "title": "x", "outlet": "Reuters", "url": "https://r", "published": "2026-11-12T08:00:00+00:00",
             "added": "2026-11-12", "region": "global", "type": "wire", "dates": ["2026-11-11"]},
            {"id": "b", "title": "y", "outlet": "Le Monde", "url": "https://l", "published": "2026-11-12T09:00:00+00:00",
             "added": "2026-11-12", "region": "europe", "type": "regional"}]
    reps = [{"date": "2026-11-12", "text": "[Reuters](https://r) reported X.", "articles": ["a"], "outlets": ["Reuters"],
             "also": [{"outlet": "AP", "url": "https://ap", "published": "2026-11-12T10:00:00+00:00", "date": "2026-11-12"}]}]
    out = export.story_for_site(story(articles=arts, reports=reps), "2026-11-12", {"a": "news", "b": "news"})
    assert out["status"] == "updated" and out["reach"] == 2 and out["outlets_period"] == 3
    assert out["reports"][0]["text"].startswith("On 12 Nov 2026,") and out["reports"][0]["also"][0]["outlet"] == "AP"
    assert out["mix"] == {"wire": 1} and out["dates"] == [{"date": "2026-11-11", "outlets": 1}]


def test_removed_sentences_are_counted_by_kind(tmp_path, monkeypatch):
    (tmp_path / "state" / "geo").mkdir(parents=True)
    (tmp_path / "state" / "geo" / "audit.json").write_text(json.dumps([
        {"date": "2026-11-12", "kind": "rejected", "text": "x", "reason": "number not in cited articles: 7"},
        {"date": "2026-11-12", "kind": "merged", "text": "y", "reason": "duplicate story merged into an existing one"},
        {"date": "2026-11-12", "text": "z", "reason": "duplicate story merged into an existing one"},     # older format
        {"date": "2026-11-12", "text": "w", "reason": "analysis word not used by the source: 'amid'"},     # older format
        {"date": "2026-11-01", "kind": "rejected", "text": "old", "reason": "no citation"}]))
    monkeypatch.setattr(export, "ROOT", tmp_path)
    assert export.guardrail_stats("geo", "2026-11-12") == {"removed": 2}
