"""Several runs a day: the rolling 24-hour window, what the AI already checked, pacing and the daily budget."""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
import yaml

import cluster
import llm
import narratives as nar
import store
from config import ROOT

FILLER = [{"id": f"f{i}", "title": f"Unrelated filler headline {i} about crop yields", "lang": "en"} for i in range(300)]


def two_outlets(art):
    a = art(1, "Port Elm harbour fire destroys Norland navy supply depot", outlet="Reuters", type="wire")
    b = art(2, "Fire at Port Elm harbour destroys Norland navy depot", outlet="BBC World")
    c = art(3, "Norland navy depot fire at Port Elm harbour: arson suspected", outlet="DW")
    return a, b, c


def sent(batches):
    return [c for b in batches for c in b["groups"]]


@pytest.fixture
def day_index(monkeypatch):
    """Word rarity as on a real day: the test headlines among many unrelated ones."""
    real = cluster.index_for
    monkeypatch.setattr(cluster, "index_for", lambda arts: real(arts + FILLER))


def test_two_outlets_hours_apart_still_make_a_story(art, day_index):
    a, b, c = two_outlets(art)
    first, _ = nar.make_batches([a], [], "geo", {})
    assert not sent(first)                                     # 09:00: one outlet, nothing to send yet
    later, cov = nar.make_batches([a, b], [], "geo", {})       # 14:00: the 24-hour window still holds the first
    assert len(sent(later)) == 1 and {x["id"] for x in sent(later)[0]["items"]} == {"a1", "a2"}


def test_groups_the_ai_already_checked_are_not_sent_again(art, day_index):
    a, b, c = two_outlets(art)
    batches, cov = nar.make_batches([a, b], [], "geo", {}, seen={"a1", "a2"})
    assert not sent(batches) and cov["already_checked"] == 1
    batches, cov = nar.make_batches([a, b, c], [], "geo", {}, seen={"a1", "a2"})
    assert len(sent(batches)) == 1                             # something new joined: send it again


def test_the_database_remembers_what_the_ai_saw_for_two_days():
    conn = store.connect()
    now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    nar.mark_seen(conn, "geo", ["old"], now - timedelta(hours=50))
    nar.mark_seen(conn, "geo", ["new"], now - timedelta(hours=3))
    nar.mark_seen(conn, "cyber", ["other-site"], now)
    seen = nar.seen_ids(conn, "geo", now)
    assert "new" in seen and "old" not in seen and "other-site" not in seen
    conn.execute("DELETE FROM ai_seen")
    conn.commit()
    conn.close()


def test_a_duplicate_pair_is_asked_about_once_a_day(art, monkeypatch):
    def s(sid, label, heads):
        return {"id": sid, "group": "namerica", "title": label, "label": label, "first_seen": "2026-11-14",
                "last_updated": "2026-11-14", "article_count": len(heads), "reports": [],
                "articles": [art(hash(sid + h) % 10**6, h, added="2026-11-14") for h in heads]}
    a = s("x1", "Microsoft global outage", ["Microsoft battles global Outlook outage", "Microsoft Teams and Outlook down worldwide"])
    b = s("x2", "Microsoft quarterly earnings", ["Microsoft earnings beat forecasts on Outlook and cloud demand",
                                                 "Microsoft Outlook revenue rises in quarterly earnings"])
    st = {"site": "geo", "narratives": [a, b], "archived": [], "last_run": {}}
    idx = cluster.index_for(a["articles"] + b["articles"] + FILLER)
    calls = []
    monkeypatch.setattr(nar, "ask_json", lambda *x: calls.append(1) or {"pairs": [{"pair": 1, "same": False}]})
    conn = store.connect()
    nar.confirm_duplicates(st, "geo", "2026-11-14", [], idx, conn)
    nar.confirm_duplicates(st, "geo", "2026-11-14", [], idx, conn)
    assert len(calls) == 1 and len(st["narratives"]) == 2
    conn.execute("DELETE FROM ai_pairs")
    conn.commit()
    conn.close()


def test_coverage_counts_what_runs_saw_once_and_what_they_did_in_total():
    st = {"coverage": []}
    for run in ({"articles": 4000, "groups": 3000, "reported_by_2": 230, "sent": 300, "calls": 8, "waiting": 40},
                {"articles": 3800, "groups": 2900, "reported_by_2": 240, "sent": 20, "calls": 1, "waiting": 0}):
        nar.save_coverage(st, "2026-11-14", run, Counter(kept=5), 0)
    day = st["coverage"][0]
    assert day["articles"] == 4000 and day["reported_by_2"] == 240        # the day's largest, not 7800
    assert day["sent"] == 320 and day["calls"] == 9 and day["waiting"] == 0 and day["kept"] == 10 and day["runs"] == 2


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1_000_000.0, "slept": []}
    monkeypatch.setattr(llm.time, "time", lambda: t["now"])

    def sleep(s):
        t["slept"].append(s)
        t["now"] += s
    monkeypatch.setattr(llm.time, "sleep", sleep)
    llm._recent.clear()
    yield t
    llm._recent.clear()


def test_pacing_waits_for_room_in_the_minute(monkeypatch, clock):
    monkeypatch.setattr(llm, "load_ai", lambda: {"limits": {"requests_per_minute": 5, "input_tokens_per_minute": 100_000,
                                                            "requests_per_day": 0, "share": 0.8}})
    for _ in range(4):                       # 80% of 5 per minute = 4
        llm._wait_for_room(1000)
    assert not clock["slept"]
    llm._wait_for_room(1000)                 # the 5th waits for the minute to pass
    assert clock["slept"] and clock["slept"][0] >= 55
    llm._recent.clear()
    clock["slept"].clear()
    llm._wait_for_room(70_000)               # one big prompt is fine on its own...
    llm._wait_for_room(20_000)               # ...but 90,000 > 80% of 100,000 in one minute: wait
    assert clock["slept"]


def test_the_daily_budget_stops_calls_and_resets_each_pacific_day(monkeypatch, tmp_path):
    usage = tmp_path / "ai-usage.json"
    monkeypatch.setattr(llm, "USAGE", usage)
    monkeypatch.setattr(llm, "load_ai", lambda: {"limits": {"requests_per_day": 500, "share": 0.8}})
    usage.write_text(json.dumps({"date": llm._pacific_day(), "requests": 400}))
    with pytest.raises(llm.LLMError, match="daily AI budget"):
        llm._wait_for_room(10)
    usage.write_text(json.dumps({"date": "2020-01-01", "requests": 400}))
    assert llm.usage_today() == 0
    llm._wait_for_room(10)
    llm._count_request()
    assert llm.usage_today() == 1
    llm._recent.clear()


def test_the_limits_in_ai_yaml_match_the_project_dashboard():
    lim = yaml.safe_load((ROOT / "config" / "ai.yaml").read_text())["limits"]
    assert lim == {"requests_per_minute": 15, "input_tokens_per_minute": 250000, "requests_per_day": 500, "share": 0.8}


def test_the_workflow_runs_every_3_hours_and_commits_website_data_once_a_day():
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    on = yaml.safe_load(wf)[True]
    assert on["schedule"] == [{"cron": "37 */3 * * *"}]
    assert "check:" not in wf and "needs: check" not in wf                # no "already built today" skip any more
    assert "path: data/sitaware.db\n          key: db-" in wf               # the database cache keeps its old key
    assert "git reset -q -- site/data" in wf                               # today's data isn't committed every run
