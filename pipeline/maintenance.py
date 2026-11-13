"""
maintenance.py - tidy the stories being tracked. Code decides; the AI is only asked to confirm or name.

Usage:
  python pipeline/maintenance.py clean            # show which stories mix unrelated events (changes nothing)
  python pipeline/maintenance.py clean --apply    # split them
  python pipeline/maintenance.py clean --no-ai    # code's suspicions only (no key needed; not for --apply)
  python pipeline/maintenance.py labels           # propose wider-story names for running stories (changes nothing)
  python pipeline/maintenance.py labels --apply   # use the proposals that pass code's checks

On GitHub: Actions tab -> "Maintenance" -> Run workflow (tick "apply" to make the changes).

LABELS. Every story has a wider-story name (shown above the day's lead headline) set on its first
day. A story that has run for days can outgrow it: "Russia hits Ukrainian infrastructure ahead of
Abu Dhabi talks" became a story about the talks. "labels" asks the AI for a neutral topic name that
covers all of a story's headlines (config/prompts/labels.md), and code keeps it only if its words
come from the headlines (the title check) and it fits at least half of them (cluster.story_support).

WHY. Before code checked the AI's "this continues story X" (see narratives.py), the AI sometimes
filed unrelated news under an old story about the same country: a Greek minister's resignation
under "Greece: migrant boat sinks off Crete", hospital strikes under "Gaza: storms and floods".

HOW "clean" decides, for each story:
  1. Its CORE: its title and the articles from the day it was first seen.
  2. Every other article that shares something with the core, or with an article already
     connected to it, stays (cluster.connected): a story may move on step by step, from talks to a
     prisoner swap to an envoys' visit. "Shares something" is the loose grouping test: two rare
     words, one of them a distinctive name (not a country, not "Trump" or "Gaza"), and no clash of
     countries.
  3. What's left shares nothing with the story: no country (in any language), no rare word. Code
     can be wrong here: a headline in another script ("Орбан", "آيزنكوت") shares no letters with
     an English story. So the AI checks code's suspects (config/prompts/cleanup.md) and only the
     headlines BOTH consider unrelated are moved. When unsure, the AI keeps them.
  4. The moved articles are grouped among themselves: a group of two or more becomes its own story
     (titled with a real headline), taking the reports that cite only its articles. Single
     leftovers leave the story, with any report that rests only on them (they still appear under
     their country's headlines).
Everything moved is written to the audit log (kind "cleanup"). Stories with fewer than 4 articles
are left alone.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from string import Template

import cluster
from config import CONFIG, load_site, sites
from llm import LLMError, ask_json
from narratives import (KEEP_ARTICLES, checked_title, home_group, load_state, note, save_audit, save_state,
                        slugify)

MIN_ARTICLES = 4      # smaller stories are left alone
LABEL_SUPPORT = 0.5   # a new wider-story name must fit at least half of the story's English headlines


def site_index(state: dict):
    """Word rarity measured on every headline of every tracked story (no database needed)."""
    arts = [a for n in state["narratives"] for a in n["articles"]]
    filler = [{"title": n["title"], "lang": "en"} for n in state["narratives"]]
    return cluster.index_for(arts + filler)


def core_of(n: dict) -> tuple[list[dict], list[dict]]:
    """(core articles, the rest). The core: what was collected on the day the story was first seen."""
    first = [a for a in n["articles"] if (a.get("added") or "") <= n["first_seen"]]
    if not first:                              # stories from before articles had dates: the oldest five
        first = sorted(n["articles"], key=lambda a: a.get("published") or "")[:5]
    ids = {id(a) for a in first}
    return first, [a for a in n["articles"] if id(a) not in ids]


def best_headline(arts: list[dict]) -> str:
    """A title for a split-off story: a real headline, from a wire or international outlet and in English if possible."""
    a = sorted(arts, key=lambda a: (a.get("type") not in ("wire", "international"), (a.get("lang") or "en") != "en"))[0]
    return a["title"][:100]


SCHEMA = {"type": "object", "properties": {"stories": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "different": {"type": "array", "items": {"type": "integer"}}},
    "required": ["id", "different"]}}}, "required": ["stories"]}
PER_CALL = 25           # stories per AI call


def suspects(state: dict, idx, site: str) -> dict[str, list[dict]]:
    """{story id: articles that share nothing with the story}, by code alone."""
    out = {}
    for n in state["narratives"]:
        if len(n["articles"]) < MIN_ARTICLES:
            continue
        core, others = core_of(n)
        names = [{"title": t, "lang": "en", "id": f"name{i}"} for i, t in enumerate(dict.fromkeys([n.get("label") or n["title"], n["title"]]))]
        _, loose = cluster.connected(idx, names + core, others, site)
        if loose:
            out[n["id"]] = loose
    return out


def confirm(state: dict, found: dict[str, list[dict]]) -> dict[str, set[str]]:
    """
    Ask the AI which suspects really are about something else. Returns {story id: article ids}.
    A story the AI doesn't answer for keeps all its articles.
    """
    template = (CONFIG / "prompts" / "cleanup.md").read_text(encoding="utf-8")
    system, prompt = (part.strip() for part in template.split("# PROMPT", 1))
    system = system.replace("# SYSTEM", "", 1).strip()
    stories = {n["id"]: n for n in state["narratives"]}
    out: dict[str, set[str]] = {}
    ids = list(found)
    for i in range(0, len(ids), PER_CALL):
        blocks, numbers, k = [], {}, 0
        for sid in ids[i:i + PER_CALL]:
            n = stories[sid]
            core, _ = core_of(n)
            lines = [f"### Story {sid}", f"title: {n['title']}", "(A) its headlines:"]
            lines += [f"  - {a['title']}" for a in core[:8]]
            lines.append("(B) suspected:")
            for a in found[sid]:
                k += 1
                numbers[k] = (sid, a["id"])
                lines.append(f"  [{k}] {a['title']}")
            blocks.append("\n".join(lines))
        try:
            answer = ask_json(system, Template(prompt).safe_substitute(stories="\n\n".join(blocks)), SCHEMA)
        except LLMError as ex:
            print(f"  AI check failed ({ex}): these stories are left as they are")
            continue
        for item in answer.get("stories") or []:
            for num in item.get("different") or []:
                if numbers.get(num, (None,))[0] == item.get("id"):       # the number must belong to that story
                    out.setdefault(item["id"], set()).add(numbers[num][1])
    return out


def clean(site: str, apply: bool = False, today: str | None = None, use_ai: bool = True) -> list[str]:
    state, site_cfg = load_state(site), load_site(site)
    today = today or datetime.now(timezone.utc).date().isoformat()
    idx = site_index(state)
    taken = {n["id"] for n in state["narratives"]} | {n["id"] for n in state["archived"]}
    audit, lines, new_stories = [], [], []
    found = suspects(state, idx, site)
    agreed = confirm(state, found) if use_ai and found else {sid: {a["id"] for a in arts} for sid, arts in found.items()}
    for n in list(state["narratives"]):
        loose = [a for a in found.get(n["id"], []) if a["id"] in agreed.get(n["id"], set())]
        kept_by_ai = len(found.get(n["id"], [])) - len(loose)
        if not loose:
            if kept_by_ai:
                lines.append(f"{n['title']}: {kept_by_ai} suspected by code, all kept after the AI check")
            continue
        loose_ids = {a["id"] for a in loose}
        groups = cluster.cluster(loose, site, idx)
        lines.append(f"{n['title']}  ({len(n['articles'])} articles): {len(loose)} about something else"
                     + (f" ({kept_by_ai} more suspected, kept after the AI check)" if kept_by_ai else ""))
        for grp in groups:
            gids = {a["id"] for a in grp}
            reps = [r for r in n["reports"] if r.get("articles") and set(r["articles"]) <= gids]
            if len(grp) >= 2:
                new_title = best_headline(grp)
                lines.append(f"    -> new story ({len(grp)} articles, {len(reps)} reports): {new_title[:90]}")
                if apply:
                    s = {"id": slugify(new_title, taken), "title": new_title, "label": new_title, "split_from": n["id"],
                         "group": home_group(site, site_cfg, new_title, grp, None),
                         "first_seen": min(a.get("added") or today for a in grp),
                         "last_updated": max(a.get("added") or today for a in grp),
                         "last_reported": max((r["date"] for r in reps), default=None),
                         "articles": sorted(grp, key=lambda a: a["published"], reverse=True)[:KEEP_ARTICLES],
                         "article_count": len(grp), "reports": reps}
                    taken.add(s["id"])
                    new_stories.append(s)
                    note(audit, "cleanup", today, n["group"], n["title"], new_title,
                         f"split off as its own story ({len(grp)} articles, {len(reps)} reports): about something else")
            else:
                lines.append(f"    -> removed: {grp[0]['title'][:90]}" + (f" (and {len(reps)} report)" if reps else ""))
                if apply:
                    note(audit, "cleanup", today, n["group"], n["title"], grp[0]["title"],
                         "removed: about something else" + (f", with {len(reps)} report(s) citing only it" if reps else ""))
            if apply:
                n["reports"] = [r for r in n["reports"] if r not in reps]
        if apply:
            # a report citing a removed article AND a kept one stays: it still rests on this story's reporting
            n["articles"] = [a for a in n["articles"] if a["id"] not in loose_ids]
            n["article_count"] = max(len(n["articles"]), n.get("article_count", 0) - len(loose))
    if apply and (new_stories or audit):
        state["narratives"] += new_stories
        save_state(site, state)
        save_audit(site, audit + _old_audit_today(site, today), today)
    return lines


def _old_audit_today(site: str, today: str) -> list[dict]:
    """save_audit replaces today's entries; keep the ones the daily run already wrote today."""
    import json
    from narratives import STATE
    path = STATE / site / "audit.json"
    return [e for e in json.loads(path.read_text(encoding="utf-8")) if e["date"] == today] if path.exists() else []


LABEL_SCHEMA = {"type": "object", "properties": {"stories": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "label": {"type": "string"}}, "required": ["id", "label"]}}}, "required": ["stories"]}


def labels(site: str, apply: bool = False, today: str | None = None) -> list[str]:
    """Wider-story names for stories running more than a day (see LABELS at the top)."""
    state = load_state(site)
    today = today or datetime.now(timezone.utc).date().isoformat()
    idx = site_index(state)
    running = [n for n in state["narratives"] if n["first_seen"] < today and len(n["articles"]) >= MIN_ARTICLES]
    if not running:
        return []
    template = (CONFIG / "prompts" / "labels.md").read_text(encoding="utf-8")
    system, prompt = (part.strip() for part in template.split("# PROMPT", 1))
    system = system.replace("# SYSTEM", "", 1).strip()
    stories = {n["id"]: n for n in running}
    proposals: dict[str, str] = {}
    for i in range(0, len(running), PER_CALL):
        blocks = []
        for n in running[i:i + PER_CALL]:
            heads = sorted(n["articles"], key=lambda a: (a.get("lang") or "en") != "en")[:12]
            blocks.append(f"### Story {n['id']}\nname now: {n.get('label') or n['title']}\nheadlines:\n"
                          + "\n".join(f"  - {a['title']}" for a in heads))
        try:
            answer = ask_json(system, Template(prompt).safe_substitute(stories="\n\n".join(blocks)), LABEL_SCHEMA)
        except LLMError as ex:
            print(f"  AI call failed ({ex}): these stories keep their names")
            continue
        for item in answer.get("stories") or []:
            if item.get("id") in stories and str(item.get("label") or "").strip():
                proposals[item["id"]] = " ".join(str(item["label"]).split())
    out, audit = [], []
    for sid, label in proposals.items():
        n = stories[sid]
        old = n.get("label") or n["title"]
        if label.lower() == old.lower():
            continue
        checked, why = checked_title(label, n["articles"])
        new_fit = cluster.story_support(idx, checked, n["articles"], site)
        old_fit = cluster.story_support(idx, old, n["articles"], site) or 0.0
        # The AI was told to keep a name that fits, so a proposal means it judged the old one stale.
        # Code only stops proposals that fit the story badly (an outlier headline) or worse than before.
        if why or new_fit is None or new_fit < LABEL_SUPPORT or new_fit < old_fit - 0.1:
            reason = why or (f"fits {new_fit:.0%} of the headlines" if new_fit is not None else "too few English headlines")
            out.append(f"  kept: {old}\n      (proposed '{label}' rejected: {reason})")
            continue
        out.append(f"{old}\n      -> {checked}  (fits {new_fit:.0%} of its headlines; the old name fit {old_fit:.0%})")
        if apply:
            note(audit, "title", today, n["group"], checked, old, "wider-story name replaced (maintenance)")
            n["label"] = checked
    if apply and audit:
        save_state(site, state)
        save_audit(site, audit + _old_audit_today(site, today), today)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tidy the tracked stories.")
    ap.add_argument("action", choices=["clean", "labels"])
    ap.add_argument("--site", choices=sites())
    ap.add_argument("--apply", action="store_true", help="make the changes (default: only show them)")
    ap.add_argument("--no-ai", action="store_true", help="clean: code's suspicions only, without the AI check")
    a = ap.parse_args()
    if a.apply and a.no_ai:
        raise SystemExit("--apply needs the AI check: code alone can't read headlines in other scripts.")
    for s in [a.site] if a.site else sites():
        lines = clean(s, a.apply, use_ai=not a.no_ai) if a.action == "clean" else labels(s, a.apply)
        verb = "Split" if a.apply else "Would split"
        renamed = sum(1 for l in lines if not l.startswith(" "))
        head = {"clean": f"{verb} or trim {sum(1 for l in lines if not l.startswith(' ') and 'kept after' not in l.split(':')[-1][:40])} stories",
                "labels": f"{'Renamed' if a.apply else 'Would rename'} {renamed} wider stories"}[a.action]
        print(f"\n=== {load_site(s)['name']}: {head} ===")
        print("\n".join(lines) or "  (none)")
    if not a.apply:
        print("\nNothing was changed. Run with --apply (or tick 'apply' in the Maintenance workflow) to make these changes.")
