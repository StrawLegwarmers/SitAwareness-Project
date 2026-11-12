"""
evaluate_grouping.py - how well does code group headlines about the same event? No AI.

Usage:
  python pipeline/evaluate_grouping.py                 # score the current settings on the labelled day
  python pipeline/evaluate_grouping.py --tune          # try other settings and rank them
  python pipeline/evaluate_grouping.py --mistakes      # show the worst merges and splits

The labelled day (tests/data/grouping_day.json.gz) holds one real day of headlines. For a sample
of 722 of them, a person checked which event each one reports (about 45 events, from 2 to 40
headlines each, in 15 languages, plus about 230 headlines that are their own event, including
look-alikes such as separate drone strikes on the same night). The rest of the day is background:
it makes word rarity realistic but isn't scored.

Scores (B-cubed, the usual measure for grouping):
  precision  for a headline, the share of its group that really is about its event (1.0 = no
             unrelated headline was mixed in). Mistakes here mislead the AI and the analyst.
  recall     for a headline, the share of its event's headlines that ended up in its group
             (1.0 = nothing split off). Mistakes here are cheaper: the AI joins groups that
             are the same event, and continuations bring the rest in later.
  F0.5       one number that weighs precision twice as much as recall.

Labels are judgment calls (is the Pope's farewell in Argentina the same event as his arrival in
Peru? here: no). To change one, edit the file's "labels" and rerun.
"""
from __future__ import annotations

import argparse
import gzip
import itertools
import json
from collections import Counter, defaultdict

import cluster
from config import ROOT

DATA = ROOT / "tests" / "data" / "grouping_day.json.gz"
SETTINGS = ("RARE", "MIN_SHARED", "MIN_SCORE", "STRONG", "LANG_COMMON")


def load(path=DATA) -> tuple[list[dict], dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    for a in data["articles"]:
        a["publisher"] = a["outlet"]
    return data["articles"], data["labels"]


def score(groups: list[list[dict]], labels: dict[str, str]) -> dict:
    """B-cubed precision, recall, F1 and F0.5 over the labelled headlines."""
    pred = {}
    for i, grp in enumerate(groups):
        for a in grp:
            if a["id"] in labels:
                pred[a["id"]] = i
    by_pred, by_gold = defaultdict(set), defaultdict(set)
    for aid, g in pred.items():
        by_pred[g].add(aid)
        by_gold[labels[aid]].add(aid)
    p = r = 0.0
    for aid in pred:
        same = by_pred[pred[aid]] & by_gold[labels[aid]]
        p += len(same) / len(by_pred[pred[aid]])
        r += len(same) / len(by_gold[labels[aid]])
    n = max(len(pred), 1)
    p, r = p / n, r / n
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    f05 = 1.25 * p * r / (0.25 * p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3), "f05": round(f05, 3)}


def run(articles: list[dict], labels: dict[str, str], **settings) -> tuple[dict, list[list[dict]]]:
    """Group the day with these settings (module constants of cluster.py), then score it."""
    old = {k: getattr(cluster, k) for k in settings}
    try:
        for k, v in settings.items():
            setattr(cluster, k, v)
        groups = cluster.cluster(articles, "geo", cluster.index_for(articles))
    finally:
        for k, v in old.items():
            setattr(cluster, k, v)
    return score(groups, labels), groups


def current() -> dict:
    return {k: getattr(cluster, k) for k in SETTINGS}


GRID = {"RARE": [1.5, 2.0, 2.5], "MIN_SHARED": [2, 3], "MIN_SCORE": [10.0, 12.0, 14.0, 16.0, 18.0],
        "STRONG": [20.0, 24.0, 30.0], "LANG_COMMON": [0.12]}


def tune(articles, labels, top: int = 12) -> list[tuple[dict, dict]]:
    results = []
    keys = list(GRID)
    for values in itertools.product(*(GRID[k] for k in keys)):
        s = dict(zip(keys, values))
        if s["STRONG"] <= s["MIN_SCORE"]:
            continue
        results.append((run(articles, labels, **s)[0], s))
    results.sort(key=lambda x: (-x[0]["f05"], -x[0]["precision"]))
    return results[:top]


def mistakes(articles, labels, groups, show: int = 12):
    """The groups mixing the most events, and the events split into the most groups."""
    text = {a["id"]: a["title"] for a in articles}
    mixed = []
    for grp in groups:
        gold = Counter(labels[a["id"]] for a in grp if a["id"] in labels)
        if len(gold) > 1:
            mixed.append((sum(gold.values()) - gold.most_common(1)[0][1], grp, gold))
    mixed.sort(key=lambda x: -x[0])
    print("\nGroups mixing different events (wrong merges):")
    for extra, grp, gold in mixed[:show]:
        print(f"  {extra} misplaced: {dict(gold)}")
        for a in grp[:6]:
            if a["id"] in labels:
                print(f"      [{labels[a['id']][:20]}] {text[a['id']][:90]}")
    pieces = defaultdict(set)
    for i, grp in enumerate(groups):
        for a in grp:
            if a["id"] in labels and not labels[a["id"]].startswith("single-"):
                pieces[labels[a["id"]]].add(i)
    print("\nEvents split into several groups (cheaper: the AI can join them):")
    for ev, gs in sorted(pieces.items(), key=lambda x: -len(x[1]))[:show]:
        print(f"  {ev}: {len(gs)} groups")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score code's headline grouping on a labelled day.")
    ap.add_argument("--tune", action="store_true", help="try other settings and rank them")
    ap.add_argument("--mistakes", action="store_true", help="show the worst merges and splits")
    a = ap.parse_args()
    arts, labs = load()
    events = Counter(v for v in labs.values() if not v.startswith("single-"))
    print(f"{len(arts)} headlines, {len(labs)} labelled: {len(events)} events and "
          f"{sum(1 for v in labs.values() if v.startswith('single-'))} single headlines")
    res, groups = run(arts, labs)
    print(f"Current settings {current()}:\n  {res}")
    if a.mistakes:
        mistakes(arts, labs, groups)
    if a.tune:
        print("\nBest settings by F0.5 (precision counts double):")
        for r, s in tune(arts, labs):
            print(f"  {r}  {s}")
