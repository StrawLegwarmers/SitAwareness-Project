"""Single-source research stories, story names, the clean-up and feed auto-disable."""
import shutil

import cluster
import maintenance
import manage_sources as ms
import narratives as nar
import store
from config import load_site

CYBER = load_site("cyber")
GEO = load_site("geo")
TODAY = "2026-11-12"
FILLER = [{"id": f"f{i}", "title": f"Unrelated filler headline {i} about crop yields", "lang": "en"} for i in range(300)]


def batch_for(groups, stories=()):
    arts = [a for items, _ in groups for a in items]
    b = {"groups": [{"items": items, "shown": items, "extra": [], "hint": hint, "research": None} for items, hint in groups],
         "stories": list(stories), "idx": cluster.index_for(arts + FILLER)}
    nar.build_prompt(CYBER, b, TODAY)
    return b


def test_promo_headlines_are_not_research():
    words = CYBER["single_source_skip"]
    assert nar.is_promo("CrowdStrike Extends the Agentic SOC to the Cloud", words, "CrowdStrike Blog")
    assert nar.is_promo("Introducing AI Kill Switch", words, "CrowdStrike Blog")
    assert not nar.is_promo("GhostFrame: A new ESXi implant linked to Settra ransomware", words, "Recorded Future Research")


def test_one_vendor_report_goes_to_the_ai(art):
    a = art(1, "GhostFrame: A new ESXi implant linked to Settra ransomware", source="Recorded Future Research",
            outlet="Recorded Future Research", site="cyber")
    batches, cov = nar.make_batches([a] + [dict(f, publisher=f"P{n}", outlet=f"P{n}") for n, f in enumerate(FILLER[:20])],
                                    [], "cyber", {}, set(CYBER["single_source_stories"]), CYBER["single_source_skip"])
    groups = [c for b in batches for c in b["groups"]]
    assert len(groups) == 1 and groups[0]["research"] == "Recorded Future Research"


def test_a_one_article_research_story_is_allowed(art):
    a = art(1, "GhostFrame: A new ESXi implant linked to Settra ransomware", source="Recorded Future Research",
            outlet="Recorded Future Research", site="cyber")
    st = {"site": "cyber", "narratives": [], "archived": [], "last_run": {}}
    b = batch_for([([a], None)])
    nar.apply_result(st, CYBER, b, {"narratives": [{"id": "", "title": "GhostFrame ESXi implant", "country": "",
                                                    "articles": [1], "reports": []}]}, TODAY, set(), [])
    assert len(st["narratives"]) == 1
    other = art(2, "Some single blog post about a new implant", source="Some Blog", outlet="Some Blog", site="cyber")
    st2 = {"site": "cyber", "narratives": [], "archived": [], "last_run": {}}
    nar.apply_result(st2, CYBER, batch_for([([other], None)]), {"narratives": [{"id": "", "title": "Implant", "country": "",
                                                                                 "articles": [1], "reports": []}]}, TODAY, set(), [])
    assert not st2["narratives"]


def story(sid, title, heads, added="2026-11-12", art=None):
    return {"id": sid, "group": "europe", "title": title, "first_seen": "2026-11-09", "last_updated": added,
            "article_count": len(heads), "reports": [],
            "articles": [art(100 + i, h, added=added) for i, h in enumerate(heads)]}


def test_the_ai_cannot_rename_a_story(art):
    """Since update 11 titles come from code (the day's lead headline); the AI's title for an existing story is ignored."""
    s = story("floods", "Gaza: severe storms and floods damage tents",
              ["Israeli strike on Nasser hospital kills six", "Strike hits Nasser medical complex in Khan Younis",
               "Six killed in strike on Nasser hospital"], art=art)
    idx = cluster.index_for(s["articles"] + FILLER)
    assert cluster.title_support(idx, s["title"], s["articles"]) == 0
    new = art(1, "Nasser hospital strike death toll rises to six", outlet="A")
    b = {"groups": [{"items": [new], "shown": [new], "extra": [], "hint": s}], "stories": [s], "idx": idx}
    nar.build_prompt(GEO, b, TODAY)
    st = {"site": "geo", "narratives": [s], "archived": [], "last_run": {}}
    nar.apply_result(st, GEO, b, {"narratives": [{"id": "floods", "title": "Nasser hospital strike", "country": "",
                                                  "articles": [1], "reports": []}]}, TODAY, set(), [])
    assert s["title"] == "Gaza: severe storms and floods damage tents"


def test_a_fitting_title_is_never_renamed(art):
    s = story("talks", "Port Elm ceasefire talks", ["Port Elm ceasefire talks resume", "Ceasefire talks in Port Elm stall",
                                                    "Port Elm talks: ceasefire draft agreed"], art=art)
    new = art(1, "Port Elm ceasefire talks end with draft", outlet="A")
    b = {"groups": [{"items": [new], "shown": [new], "extra": [], "hint": s}], "stories": [s],
         "idx": cluster.index_for(s["articles"] + [new] + FILLER)}
    nar.build_prompt(GEO, b, TODAY)
    st = {"site": "geo", "narratives": [s], "archived": [], "last_run": {}}
    nar.apply_result(st, GEO, b, {"narratives": [{"id": "talks", "title": "Something else entirely", "country": "",
                                                  "articles": [1], "reports": []}]}, TODAY, set(), [])
    assert s["title"] == "Port Elm ceasefire talks"


def test_clean_up_splits_unrelated_articles(art, tmp_path, monkeypatch):
    core = [art(i, f"Hungary: Orbán's brother arrested in people-smuggling probe {i}", added="2026-11-09") for i in range(4)]
    follow = [art(10, "Court jails Orbán's brother pending trial in Hungary", added="2026-11-11")]
    other = [art(20, "Thomas Markle jailed after cutting off ankle monitor, US judge says", added="2026-11-11", outlet="X"),
             art(21, "US judge jails Thomas Markle over ankle monitor", added="2026-11-11", outlet="Y")]
    s = {"id": "orban", "group": "europe", "title": "Orbán's brother arrested in Hungary", "first_seen": "2026-11-09",
         "last_updated": "2026-11-11", "article_count": 7, "articles": core + follow + other,
         "reports": [{"date": "2026-11-11", "text": "[X](https://x) reported a jailing.", "articles": ["a20"], "outlets": ["X"]}]}
    state = {"site": "geo", "narratives": [s], "archived": [], "last_run": {}}
    monkeypatch.setattr(maintenance, "load_state", lambda site: state)
    saved = {}
    monkeypatch.setattr(maintenance, "save_state", lambda site, st: saved.update(st=st))
    monkeypatch.setattr(maintenance, "save_audit", lambda site, entries, today: saved.update(audit=entries))
    monkeypatch.setattr(maintenance, "_old_audit_today", lambda site, today: [])
    monkeypatch.setattr(maintenance, "site_index", lambda st: cluster.index_for(core + follow + other + FILLER))
    lines = maintenance.clean("geo", apply=True, today=TODAY)          # the mock AI confirms code's suspicions
    titles = [n["title"] for n in saved["st"]["narratives"]]
    assert len(s["articles"]) == 5 and not s["reports"]
    assert any("Markle" in t for t in titles) and any("split off" in e["reason"] for e in saved["audit"]), lines


def test_feeds_failing_for_a_week_are_turned_off(tmp_path, monkeypatch):
    conn = store.connect()
    for name in ("geo", "cyber"):
        shutil.copy(ms.CONFIG / name / "sources.yaml", tmp_path / f"{name}.yaml")
    monkeypatch.setattr(ms, "sources_path", lambda site: tmp_path / f"{site}.yaml")
    monkeypatch.setattr(ms, "validate", lambda site: [])
    first = ms.entries("geo")[0][1]
    conn.execute("DELETE FROM feed_state")
    conn.execute("INSERT INTO feed_state(feed, last_ok, last_error, fails_in_row) VALUES (?, ?, ?, ?)",
                 (first["feed"], "2026-10-01T00:00:00+00:00", "HTTP 403", 9))
    out = ms.auto_disable(conn, days=7, failures=5)
    assert "turned off" in out
    line = [l for l in (tmp_path / "geo.yaml").read_text().splitlines() if first["feed"] in l][0]
    assert "enabled: false" in line and "Auto-disabled" in line
    assert "nothing was turned off" not in out
    conn.rollback()
    conn.close()


def test_mass_failures_disable_nothing(tmp_path, monkeypatch):
    conn = store.connect()
    for name in ("geo", "cyber"):
        shutil.copy(ms.CONFIG / name / "sources.yaml", tmp_path / f"{name}.yaml")
    monkeypatch.setattr(ms, "sources_path", lambda site: tmp_path / f"{site}.yaml")
    conn.execute("DELETE FROM feed_state")
    for _, item in ms.entries("geo"):
        if item.get("feed"):
            conn.execute("INSERT OR REPLACE INTO feed_state(feed, last_ok, last_error, fails_in_row) VALUES (?, ?, ?, ?)",
                         (item["feed"], "2026-10-01T00:00:00+00:00", "ConnectTimeout", 9))
    out = ms.auto_disable(conn)
    assert "nothing was turned off" in out
    assert "Auto-disabled" not in (tmp_path / "geo.yaml").read_text()
    conn.rollback()
    conn.close()
