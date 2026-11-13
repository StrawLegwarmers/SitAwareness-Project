"""Lead-headline titles and wider stories, continuation checks per headline, topics, duplicates, corrections."""
import cluster
import countries
import maintenance
import narratives as nar
from config import ROOT, load_site

GEO = load_site("geo")
TODAY = "2026-11-13"
FILLER = [{"id": f"f{i}", "title": f"Unrelated filler headline {i} about crop yields", "lang": "en"} for i in range(300)]


def fairford(art):
    heads = ["US charges three men over plot to attack RAF Fairford", "RAF Fairford plot: three charged in New York",
             "Three Iran-backed men charged over RAF Fairford attack plot", "US withdraws aircraft from RAF Fairford"]
    return {"id": "fairford", "group": "europe", "title": "RAF Fairford attack plot", "label": "RAF Fairford attack plot",
            "first_seen": "2026-11-10", "last_updated": "2026-11-12", "article_count": 4, "reports": [],
            "articles": [art(100 + i, h, added="2026-11-11", outlet=f"Old {i}") for i, h in enumerate(heads)]}


def test_one_unrelated_headline_cannot_ride_along_with_a_continuation(art):
    s = fairford(art)
    good = art(1, "Guardian: US terror case sheds light on RAF Fairford arrests", outlet="The Guardian")
    bad = art(2, "FSB foils terror plot at Stavropol shopping mall", outlet="TASS", type="state-media")
    idx = cluster.index_for(s["articles"] + [good, bad] + FILLER)
    b = {"groups": [{"items": [good], "shown": [good], "extra": [], "hint": s, "outlets": 1},
                    {"items": [bad], "shown": [bad], "extra": [], "hint": None, "outlets": 1}],
         "stories": [s], "idx": idx}
    nar.build_prompt(GEO, b, TODAY)
    st = {"site": "geo", "narratives": [s], "archived": [], "last_run": {}}
    audit = []
    nar.apply_result(st, GEO, b, {"narratives": [{"id": "fairford", "title": "", "country": "", "topic": "security",
        "articles": [1, 2], "reports": [{"text": "[2] reported that the FSB foiled a plot.", "articles": [2]},
                                        {"text": "[1] reported that a US terror case sheds light on the RAF Fairford arrests.", "articles": [1]}]}]},
        TODAY, set(), audit)
    titles = [a["title"] for a in s["articles"]]
    assert good["title"] in titles and bad["title"] not in titles
    assert len(s["reports"]) == 1 and "Fairford" in s["reports"][0]["text"]
    assert any(e["kind"] == "skipped" and "Stavropol" in e["reason"] for e in audit)
    assert any(e["kind"] == "rejected" and "doesn't belong" in e["reason"] for e in audit)


def nvidia_day(art):
    heads = [("Nvidia CEO Jensen Huang resigns; CFO Colette Kress named interim chief", "Reuters", "wire"),
             ("Jensen Huang steps down as Nvidia CEO, Colette Kress to lead", "BBC", "international"),
             ("Nvidia's Jensen Huang resigns as chief executive, Kress interim CEO", "CNBC", "regional"),
             ("Colette Kress takes over at Nvidia after Jensen Huang resigns", "DW", "international"),
             ("Seoul shares drop nearly 1 pct following Nvidia jitters", "Yonhap", "local")]
    return [art(10 + i, h, outlet=o, type=t, added=TODAY) for i, (h, o, t) in enumerate(heads)]


def test_lead_headline_is_the_one_most_outlets_back(art):
    day = nvidia_day(art)
    idx = cluster.index_for(day + FILLER)
    best, backing, others = cluster.lead_headline(idx, day)
    assert best is not None and "Seoul" not in best["title"] and backing >= 2 and others == 4
    assert cluster.lead_headline(idx, day[:2])[0] is None                 # too few articles that day
    odd = [art(30 + i, h, outlet=f"O{i}", added=TODAY) for i, h in enumerate(
        ["Port Elm ferry strike enters day three", "Norland coalition talks stall", "Sudmark floods displace 400"])]
    assert cluster.lead_headline(cluster.index_for(odd + FILLER), odd)[0] is None   # nothing backs any of them


def test_lead_titles_keep_the_wider_story(art):
    day = nvidia_day(art)
    s = {"id": "nvidia", "group": "namerica", "title": "Nvidia CEO affair and espionage claims",
         "label": "Nvidia CEO affair and espionage claims", "first_seen": "2026-11-09", "last_updated": TODAY,
         "article_count": 40, "reports": [], "articles": day}
    st = {"site": "geo", "narratives": [s], "archived": [], "last_run": {}}
    assert nar.lead_titles(st, "geo", TODAY, cluster.index_for(day + FILLER)) == 1
    assert "Kress" in s["title"] and s["label"] == "Nvidia CEO affair and espionage claims"
    assert s["title_from"]["outlet"] in {"Reuters", "BBC", "CNBC", "DW"}


def test_old_stories_get_a_wider_story_name_from_their_first_title(tmp_path, monkeypatch):
    path = tmp_path / "geo" / "narratives.json"
    path.parent.mkdir()
    path.write_text('{"site": "geo", "last_run": {}, "archived": [], "narratives": [{"id": "x", "title": "FSB foils plot",'
                    ' "previous_titles": ["US aircraft withdrawn from UK base"], "articles": [], "reports": []}]}')
    monkeypatch.setattr(nar, "STATE", tmp_path)
    assert nar.load_state("geo")["narratives"][0]["label"] == "US aircraft withdrawn from UK base"


def new_story_batch(art, n=2):
    arts = [art(i + 1, f"Studio auctions Darth Vader lightsaber for record sum {i}", outlet=f"O{i}") for i in range(n)]
    b = {"groups": [{"items": arts, "shown": arts, "extra": [], "hint": None, "outlets": n}], "stories": [],
         "idx": cluster.index_for(arts + FILLER)}
    nar.build_prompt(GEO, b, TODAY)
    return b


def run_new(art, **item):
    st = {"site": "geo", "narratives": [], "archived": [], "last_run": {}}
    audit = []
    answer = {"id": "", "title": "Lightsaber auction record", "country": "", "articles": [1, 2],
              "reports": [{"text": "[1] reported that a lightsaber was auctioned.", "articles": [1]}]} | item
    nar.apply_result(st, GEO, new_story_batch(art), {"narratives": [answer]}, TODAY, set(), audit)
    return st, audit


def test_topics_outside_the_site_are_not_created(art):
    for topic in ("entertainment", "business", "markets", "health", "sport", "celebrity"):
        st, audit = run_new(art, topic=topic)
        assert not st["narratives"], topic
        assert any(f"topic: {topic}" in e["reason"] for e in audit)
    st, _ = run_new(art, topic="business-strategic")
    assert st["narratives"] and st["narratives"][0]["topic"] == "business-strategic"
    st, _ = run_new(art)                                  # no topic at all: kept (the other filters still apply)
    assert st["narratives"]


def test_a_group_the_ai_ignored_is_logged(art):
    b = new_story_batch(art)
    audit = []
    counts = nar.apply_result({"site": "geo", "narratives": [], "archived": [], "last_run": {}}, GEO, b,
                              {"narratives": []}, TODAY, set(), audit)
    assert counts["dropped"] == 1 and audit[0]["kind"] == "dropped" and "Vader" in audit[0]["text"]


def test_the_ai_confirms_duplicates_code_suspects(art):
    def s(sid, label, heads, first):
        return {"id": sid, "group": "namerica", "title": label, "label": label, "first_seen": first, "last_updated": TODAY,
                "article_count": len(heads), "reports": [],
                "articles": [art(hash(sid + h) % 10**6, h, added=TODAY, lang="en") for h in heads]}
    a = s("ms-1", "Global Microsoft outage", ["Microsoft battles global Outlook outage", "Microsoft Teams and Outlook down worldwide"], "2026-11-13")
    b = s("ms-2", "Microsoft outage in Outlook", ["Microsoft no logra recuperar Outlook tras la caída global"], "2026-11-13")
    c = s("ms-3", "Microsoft quarterly earnings beat", ["Microsoft earnings beat forecasts on cloud demand"], "2026-11-13")
    st = {"site": "geo", "narratives": [a, b, c], "archived": [], "last_run": {}}
    idx = cluster.index_for([x for n in (a, b, c) for x in n["articles"]] + FILLER)
    assert cluster.close(idx, a["articles"][0], b["articles"][0]) is False      # the word test alone misses it
    audit = []
    done = nar.confirm_duplicates(st, "geo", TODAY, audit, idx)
    ids = {n["id"] for n in st["narratives"]}
    assert done and "ms-3" in ids and len(ids) == 2
    assert any(e["kind"] == "merged" and "confirmed by the AI" in e["reason"] for e in audit)


def test_corrections_hide_merge_and_remove_a_headline(art, tmp_path, monkeypatch):
    s = fairford(art)
    bad = art(9, "FSB foils terror plot at Stavropol shopping mall", outlet="TASS", added=TODAY)
    s["articles"].append(bad)
    s["reports"] = [{"date": TODAY, "text": "[TASS](https://x) reported a plot.", "articles": ["a9"], "outlets": ["TASS"]}]
    s["previous_titles"], s["title"] = [s["title"]], bad["title"]
    vader = {"id": "vader", "group": "global", "title": "Lightsaber auction", "first_seen": TODAY, "last_updated": TODAY,
             "article_count": 2, "reports": [], "articles": [art(50, "Lightsaber sold", added=TODAY)]}
    dup = {"id": "fairford-2", "group": "europe", "title": "Fairford plot charges", "first_seen": TODAY, "last_updated": TODAY,
           "article_count": 1, "reports": [], "articles": [art(60, "Fairford plot: three charged", added=TODAY)]}
    (tmp_path / "geo").mkdir()
    (tmp_path / "geo" / "corrections.yaml").write_text(
        "remove_headline:\n  - {story: fairford, headline: \"FSB foils terror plot\"}\n"
        "merge:\n  - {stories: [fairford, Fairford plot charges]}\n"
        "hide:\n  - {story: vader}\n", encoding="utf-8")
    monkeypatch.setattr(nar, "CONFIG", tmp_path)
    st = {"site": "geo", "narratives": [s, vader, dup], "archived": [], "last_run": {}}
    audit = []
    nar.apply_corrections(st, "geo", TODAY, audit)
    assert [n["id"] for n in st["narratives"]] == ["fairford"]
    assert s["title"] == "RAF Fairford attack plot" and not s["reports"]
    assert all("Stavropol" not in a["title"] for a in s["articles"]) and any("three charged" in a["title"] for a in s["articles"])
    assert st["archived"][0]["id"] == "vader" and st["archived"][0]["hidden"]
    assert sum(e["kind"] == "correction" for e in audit) == 3
    before = len(audit)
    nar.apply_corrections(st, "geo", TODAY, audit)          # rules left in place do nothing the second time
    assert len(audit) == before


def test_the_subject_named_in_the_title_decides_the_region():
    g = countries.load("geo")
    title = "Iranian men found guilty in UK of assisting Iranian intelligence"
    p = g.place(g.score(["Two Iranian men guilty of spying for Iran on UK journalists"] * 3, title), "global", title, "uk")
    assert p["region"] == g.region("uk") and p["lead"] == "uk" and "iran" in p["countries"]


def test_a_new_wider_story_name_must_fit_the_story(art, monkeypatch):
    s = fairford(art)
    s["articles"] += [art(120 + i, h, added=TODAY, outlet=f"N{i}") for i, h in enumerate(
        ["UK police link RAF Fairford suspects to Iran handler", "RAF Fairford case: New York prison link"])]
    s["first_seen"] = "2026-11-10"
    st = {"site": "geo", "narratives": [s], "archived": [], "last_run": {}}
    monkeypatch.setattr(maintenance, "load_state", lambda site: st)
    monkeypatch.setattr(maintenance, "site_index", lambda state: cluster.index_for(s["articles"] + FILLER))
    saved = {}
    monkeypatch.setattr(maintenance, "save_state", lambda site, state: saved.update(st=state))
    monkeypatch.setattr(maintenance, "save_audit", lambda site, entries, today: saved.update(audit=entries))
    monkeypatch.setattr(maintenance, "_old_audit_today", lambda site, today: [])
    monkeypatch.setattr(maintenance, "ask_json", lambda *a: {"stories": [{"id": "fairford", "label": "Stavropol shopping mall plot"}]})
    lines = maintenance.labels("geo", apply=True, today=TODAY)
    assert s["label"] == "RAF Fairford attack plot" and "rejected" in lines[0]
    monkeypatch.setattr(maintenance, "ask_json", lambda *a: {"stories": [{"id": "fairford", "label": "RAF Fairford plot case"}]})
    maintenance.labels("geo", apply=True, today=TODAY)
    assert s["label"] == "RAF Fairford plot case" and saved["audit"][0]["kind"] == "title"


def test_story_cards_show_the_wider_story_and_no_totals():
    js = (ROOT / "site" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "in total" not in js and "data-wider" in js and "Wider story" in js
    assert "new for you" not in js and "since your last visit</span>" not in js     # removed: less clutter
    assert '${plural(outlets, "outlet")} ${P.since}' not in js                      # no "N outlets today" on cards
