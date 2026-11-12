import cluster
import narratives as nar
from config import load_site

SITE = load_site("geo")
TODAY = "2026-11-12"


FILLER = [{"id": f"f{i}", "title": f"Unrelated filler headline {i} about crop yields", "lang": "en"} for i in range(300)]


def make_batch(groups, stories=()):
    """groups: list of (articles, hinted story or None). Numbers articles as build_prompt does."""
    arts = [a for items, _ in groups for a in items]
    filler = FILLER
    batch = {"groups": [{"items": items, "shown": items, "extra": [], "hint": hint} for items, hint in groups],
             "stories": list(stories), "idx": cluster.index_for(arts + filler)}
    nar.build_prompt(SITE, batch, TODAY)
    return batch


def state(*stories):
    return {"site": "geo", "narratives": list(stories), "archived": [], "last_run": {}}


def run(st, batch, result):
    audit = []
    counts = nar.apply_result(st, SITE, batch, {"narratives": result}, TODAY, set(), audit)
    return counts, audit


def test_cite_inserts_real_links():
    refs = {1: {"outlet": "Reuters", "url": "https://r.example/1"}, 2: {"outlet": "Outlet B", "url": "https://b.example/2"}}
    assert nar.cite("[1] reported that X.", refs) == "[Reuters](https://r.example/1) reported that X."
    assert nar.cite("[1][2] reported that X.", refs) == "[Reuters](https://r.example/1), [Outlet B](https://b.example/2) reported that X."
    assert nar.cite("X happened, officials said [1].", refs) == "X happened, officials said ([Reuters](https://r.example/1))."
    assert nar.cite("[99] reported X.", refs) == "reported X."


def test_new_story_with_a_checked_report(art):
    a1 = art(1, "Norland coast guard says four ships hit mines near Port Elm", outlet="Reuters")
    a2 = art(2, "Four ships hit mines near Port Elm, Norland says", outlet="AP")
    st = state()
    b = make_batch([([a1, a2], None)])
    counts, audit = run(st, b, [{"id": "", "title": "Port Elm ships and mines", "country": "",
                                 "articles": [1, 2], "reports": [{"text": "[1] reported that four ships hit mines near Port Elm.", "articles": [1]}]}])
    assert counts["new"] == 1 and counts["kept"] == 1
    n = st["narratives"][0]
    assert n["title"] == "Port Elm ships and mines" and len(n["articles"]) == 2
    r = n["reports"][0]
    assert r["text"].startswith("[Reuters](https://example.com/1) reported") and r["published"] == a1["published"]


def test_a_repeat_from_another_outlet_becomes_corroboration(art):
    a1 = art(1, "Norland coast guard says four ships hit mines near Port Elm", outlet="Reuters")
    a2 = art(2, "Norland coast guard says four ships hit mines near Port Elm harbour", outlet="Outlet B")
    st = state()
    b = make_batch([([a1, a2], None)])
    counts, _ = run(st, b, [{"id": "", "title": "Port Elm shipping incidents", "country": "", "articles": [1, 2], "reports": [
        {"text": "[1] reported that four ships hit mines near Port Elm.", "articles": [1]},
        {"text": "[2] reported that four ships hit mines near Port Elm.", "articles": [2]}]}])
    r = st["narratives"][0]["reports"]
    assert len(r) == 1 and counts["corroborated"] == 1 and r[0]["also"][0]["outlet"] == "Outlet B"


def test_failed_guardrail_is_audited_as_rejected(art):
    a1, a2 = art(1, "Four ships hit mines near Port Elm", outlet="A"), art(2, "Ships hit mines near Port Elm", outlet="B")
    st = state()
    b = make_batch([([a1, a2], None)])
    counts, audit = run(st, b, [{"id": "", "title": "Port Elm shipping incidents", "country": "", "articles": [1, 2], "reports": [
        {"text": "[1] reported that six ships hit mines near Port Elm.", "articles": [1]}]}])
    assert counts["rejected"] == 1
    assert [e["kind"] for e in audit if e["kind"] == "rejected"] == ["rejected"]


def test_unsupported_continuation_is_not_glued_onto_an_old_story(art):
    old = {"id": "greece-boat", "group": "europe", "title": "Greece: migrant boat sinks off Crete", "first_seen": "2026-11-09",
           "last_updated": "2026-11-11", "article_count": 1, "reports": [],
           "articles": [art(9, "Migrant boat sinks off Crete, 13 dead", added="2026-11-09")]}
    a1 = art(1, "Greek deputy minister resigns over daughter's handball team enrolment", outlet="A")
    a2 = art(2, "Greek deputy minister quits after handball enrolment scandal", outlet="B")
    st = state(old)
    b = make_batch([([a1, a2], None)])
    counts, audit = run(st, b, [{"id": "greece-boat", "title": old["title"], "country": "Greece", "articles": [1, 2], "reports": []}])
    assert len(old["articles"]) == 1
    assert any(e["kind"] == "skipped" and "continuation" in e["reason"] for e in audit)
    assert counts["new"] == 1                                  # it became its own story


def test_suggested_continuation_is_accepted(art):
    old = {"id": "boat", "group": "europe", "title": "Port Elm shipping incidents", "first_seen": "2026-11-09",
           "last_updated": "2026-11-11", "article_count": 1, "reports": [],
           "articles": [art(9, "Four ships hit mines near Port Elm", added="2026-11-09")]}
    a1 = art(1, "Salvage begins near Port Elm after mine strikes", outlet="A")
    st = state(old)
    b = make_batch([([a1], old)], [old])
    run(st, b, [{"id": "boat", "title": old["title"], "country": "", "articles": [1], "reports": []}])
    assert len(old["articles"]) == 2 and old["last_updated"] == TODAY


def test_offtopic_new_story_is_not_created(art):
    a1, a2 = art(1, "Stars walk the red carpet at Cairo film festival", outlet="A"), art(2, "Cairo film festival opens", outlet="B")
    st = state()
    b = make_batch([([a1, a2], None)])
    counts, audit = run(st, b, [{"id": "", "title": "Cairo International Film Festival opening", "country": "Egypt",
                                 "articles": [1, 2], "reports": []}])
    assert not st["narratives"] and counts["skipped"] == 1


def test_story_needs_two_articles(art):
    st = state()
    b = make_batch([([art(1, "Lone headline about Port Elm")], None)])
    counts, audit = run(st, b, [{"id": "", "title": "Port Elm", "country": "", "articles": [1], "reports": []}])
    assert not st["narratives"] and audit[0]["kind"] == "skipped"


def test_strange_answers_are_ignored(art):
    st = state()
    b = make_batch([([art(1, "Headline one about Port Elm"), art(2, "Headline two about Port Elm")], None)])
    run(st, b, ["not a dict", {"id": None, "articles": ["x", 99, 1], "reports": [None, {"text": None}]}])
    assert not st["narratives"]


def test_merge_survives_stories_without_reports(art):
    a = {"id": "a", "group": "europe", "title": "Port Elm shipping incidents", "first_seen": "2026-11-10", "last_updated": TODAY,
         "last_reported": None, "article_count": 2, "reports": [],
         "articles": [art(1, "Four ships hit mines near Port Elm, Norland says"), art(2, "Norland: ships hit mines near Port Elm")]}
    b = {"id": "b", "group": "europe", "title": "Port Elm mine strikes", "first_seen": TODAY, "last_updated": TODAY,
         "last_reported": None, "article_count": 2, "reports": [],
         "articles": [art(3, "Ships hit mines near Port Elm, Norland coast guard says"), art(4, "Four ships hit mines near Port Elm")]}
    st = state(a, b)
    idx = cluster.index_for(a["articles"] + b["articles"] + FILLER)
    done = nar.merge_duplicates(st, "geo", TODAY, [], idx)
    assert len(done) == 1 and len(st["narratives"]) == 1


def test_split_and_retry_when_the_answer_is_cut_off(art, monkeypatch):
    monkeypatch.setenv("MOCK_MAX_GROUPS", "1")
    monkeypatch.setattr(nar.time, "sleep", lambda s: None)
    groups = [([art(1, "Port Elm mines one", outlet="A"), art(2, "Port Elm mines two", outlet="B")], None),
              ([art(3, "Lindau shooting one", outlet="C"), art(4, "Lindau shooting two", outlet="D")], None)]
    b = make_batch(groups)
    done, failed, errors = nar.ask_batch(SITE, b, TODAY, {"pause_seconds": 0}, "call 1")
    assert len(done) == 2 and not failed and not errors


def test_status_from_dates():
    n = {"first_seen": "2026-11-10", "last_updated": TODAY, "last_reported": "2026-11-10", "reports": []}
    assert nar.status_of(n, TODAY) == "covered"
    assert nar.status_of(n | {"last_reported": TODAY}, TODAY) == "updated"
    assert nar.status_of(n | {"first_seen": TODAY}, TODAY) == "new"
    assert nar.status_of(n | {"last_updated": "2026-11-10"}, TODAY) == "unchanged"
