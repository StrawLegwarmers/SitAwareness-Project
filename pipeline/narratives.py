"""
narratives.py - group the day's articles into stories, and collect what each outlet REPORTED.

Usage (from the repo folder):
  python pipeline/narratives.py                             # every site
  python pipeline/narratives.py --site geo                  # one site
  python pipeline/narratives.py --site geo --group europe   # only articles from one group (saves quota)
  python pipeline/narratives.py --site geo --dry-run        # build the prompts, don't call the AI
  python pipeline/narratives.py --site geo --show           # print what's being tracked
  python pipeline/narratives.py --site geo --audit          # what the guardrails removed

This is a COLLECTION tool, not an analysis tool. The work is split:
  - CODE groups the headlines first (cluster.py): which articles are about the same event,
    and which tracked story each group probably continues. Cheap, complete, repeatable.
  - The AI checks each group and writes one-sentence REPORTS: "[12] reported that ..."
    (attributed, nothing added). It sees about 40 groups per call, so nothing gets crowded out.

Everything else is plain code, and the code checks the AI's work:
  1. Reports must cite real articles; the AI writes [12], the code inserts the real link and
     the date the article was published ("On 12 Nov 2026, Reuters reported that ...").
  2. Every report passes guardrails.py (attribution, numbers, names, no analysis words).
     Failures are removed and logged to state/<site>/audit.json.
  3. Story names are checked too: a bad one is replaced by a real headline. Each story has a
     wider-story name (set when it starts) and a title, the day's lead headline, picked by code.
  4. A report that repeats a fact already collected doesn't appear twice: the new outlet is
     added to the earlier report as "also reported by" (corroboration).
  5. Ranking is by how many different outlets (and regions) reported a story: counted, not judged.
  6. The website always shows the original headlines next to the AI's sentences.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
import traceback
from collections import Counter
from datetime import datetime, timedelta, timezone
from string import Template

import cluster
import content
import countries as gazetteer
import guardrails
import store
from config import CONFIG, ROOT, load_ai, load_publishers, load_site, sites
from llm import LLMError, ask_json
from mentioned_dates import dates_in

STATE = ROOT / "state"
KEEP_ARTICLES = 40    # per story, newest first
KEEP_REPORTS = 40     # per story, newest first (so earlier days' reporting stays visible)
KEEP_ARCHIVED = 100
AUDIT_DAYS = 7

# Duplicate checks. Measured on real data: two different stories shared at most
# 32% of their words; a true duplicate shared 63%. 0.5 sits safely between the two.
SAME_STORY = 0.5      # a "new" story this similar to an existing one is merged into it
# A story whose headlines are mostly not in English can be described by very few English words,
# so two unrelated stories can share "50%" of them by accident. So a merge also needs:
MIN_WORDS = 6         # ...enough words on BOTH sides to compare
MIN_SHARED = 3        # ...at least this many words in common
#                     # ...and at least one country in common, when both stories name countries
SAME_REPORT = 0.8     # a report this similar to one already in the story is skipped
SAME_FACTS = 0.7      # ...or, from a new outlet, added to it as "also reported by" (see same_facts)
MERGE_SHARE = 0.5     # two tracked stories are merged when this share of headlines match (cluster.py)
COVERAGE_DAYS = 14    # days of collection statistics kept in the state file
RETRY_MAX = 1500      # articles carried over to the next run when the AI call limit is reached
DUP_PAIRS = 30        # at most this many "same event?" questions in the duplicate check after the calls
DUP_COMMON = 6        # a name shared by more stories than this (Trump, Gaza) doesn't make two stories look alike
DUP_OVERLAP = 0.3     # ...and their core names must overlap this much (shared / sqrt(a * b))

PUBLISHERS = load_publishers()


def publisher(outlet: str) -> str:
    """'BBC Africa' -> 'BBC'. Several feeds of one organisation count as ONE outlet (config/publishers.yaml)."""
    return PUBLISHERS.get(outlet, outlet)


def words(text: str) -> set[str]:
    """The meaningful words of a text, roughly stemmed: what two texts are compared on."""
    return {guardrails.stem(w) for w in guardrails.content_words(strip_links(text), set())}


def overlap(a: set[str], b: set[str]) -> float:
    """Share of the smaller set's words that are also in the other (0 = nothing in common, 1 = all)."""
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def story_words(title: str, articles: list[dict]) -> set[str]:
    """A story's fingerprint: its title plus its English headlines."""
    return words(title + " " + " ".join(a["title"] for a in articles[:12] if (a.get("lang") or "en") == "en"))

# What a story is about. The AI must pick one for every story (rule 13 of the prompt); each site
# keeps only the topics listed in its site.yaml ("topics"), and code drops new stories with any other.
# Choosing a label is more reliable than remembering a list of things to skip.
TOPICS = [
    "conflict", "security", "diplomacy", "politics", "elections", "justice", "economy", "energy",
    "infrastructure", "migration", "humanitarian", "disaster", "health-emergency", "cyber",
    "technology-policy", "crime", "business-strategic", "markets-strategic",
    "business", "markets", "health", "science", "technology", "sport", "entertainment", "culture",
    "celebrity", "lifestyle", "weather", "other",
]

# The exact JSON shape we want back. The model is forced to follow it (structured output).
SCHEMA = {
    "type": "object",
    "properties": {
        "narratives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "existing story id, or empty string if new"},
                    "title": {"type": "string"},
                    "country": {"type": "string", "description": "country the story is mainly about, or empty"},
                    "topic": {"type": "string", "enum": TOPICS},
                    "articles": {"type": "array", "items": {"type": "integer"}},
                    "reports": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {"text": {"type": "string"},
                                           "articles": {"type": "array", "items": {"type": "integer"}}},
                            "required": ["text", "articles"],
                        },
                    },
                },
                "required": ["id", "title", "country", "topic", "articles", "reports"],
            },
        }
    },
    "required": ["narratives"],
}


# ── State: the stories we track (small JSON, committed to Git) ──────────────

def load_state(site: str) -> dict:
    path = STATE / site / "narratives.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else \
        {"site": site, "last_run": {}, "narratives": [], "archived": []}
    for n in state["narratives"]:
        # Early versions stored AI-written summaries that were never checked. Keep the story and its
        # articles, but drop that unverified text: only guardrail-checked reports from now on.
        n.setdefault("reports", [])
        for old in ("summary", "today", "importance", "countries", "history", "new_today"):
            n.pop(old, None)
        # Two names per story: "label", the wider story (set when it starts, stable), and "title",
        # the day's lead headline (finalize). Stories from before both existed: the first title they had.
        n.setdefault("label", (n.get("previous_titles") or [n["title"]])[0])
    return state


def save_state(site: str, state: dict):
    path = STATE / site / "narratives.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")


# Every audit entry has a "kind", so the website can count what matters:
#   rejected    a sentence that failed a guardrail (the number shown as "sentences removed")
#   title       a story title replaced by a real headline
#   skipped     a story the AI proposed that code didn't create or extend
#   dropped     a group of 2+ outlets the AI returned no story for (judged off-topic or not news)
#   merged      a duplicate story merged into another
#   correction  your manual fix from corrections.yaml
#   commentary  a report removed because it rested only on opinion or analysis
#   info        anything else worth seeing in --audit
def note(audit: list[dict], kind: str, today: str, group: str, story: str, text: str, reason: str):
    audit.append({"date": today, "kind": kind, "group": group, "story": story, "text": text, "reason": reason})


def save_audit(site: str, entries: list[dict], today: str):
    """Everything the guardrails removed, kept for AUDIT_DAYS days. Read it with --audit."""
    path = STATE / site / "audit.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    cutoff = (datetime.fromisoformat(today) - timedelta(days=AUDIT_DAYS)).date().isoformat()
    keep = [e for e in old if e["date"] >= cutoff and e["date"] != today] + entries
    path.write_text(json.dumps(keep, indent=1, ensure_ascii=False), encoding="utf-8")


# ── Step 1: pick articles ───────────────────────────────────────────────────

def group_of(a: dict, site_cfg: dict) -> str:
    """The group (site.yaml) an article's source belongs to: by section if groups have sections, else by region."""
    for g in site_cfg["groups"]:
        if g.get("sections") and a.get("section") in g["sections"]:
            return g["id"]
    ids = [g["id"] for g in site_cfg["groups"]]
    return a.get("region") if a.get("region") in ids else ids[-1]


def select_articles(conn, site: str, site_cfg: dict, since: str, ai: dict, only_group: str | None = None,
                    retry: list[str] | None = None) -> list[dict]:
    """
    New NEWS articles from every group's sources since the last run, at most N per source,
    plus any left over from the last run (when it hit the AI call limit).

    Fair trimming: if there are more than max_per_run, we keep every source's newest article
    first, then every source's 2nd newest, and so on (ORDER BY rn). So the cap trims each source
    a little, instead of cutting off everything published before a certain hour.
    """
    groups = [g for g in site_cfg["groups"] if not only_group or g["id"] == only_group]
    sections = [x for g in groups for x in g.get("sections") or []]
    regions = [g["id"] for g in groups if not g.get("sections")]
    where = " OR ".join(([f"section IN ({','.join('?' * len(sections))})"] if sections else []) +
                        ([f"region IN ({','.join('?' * len(regions))})"] if regions else []))
    # Only NEWS goes to the AI. Opinion and analysis (content.py) are never restated as fact.
    rows = conn.execute(
        f"""SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY source ORDER BY published DESC) AS rn
                FROM articles WHERE site = ? AND first_seen > ? AND ({where})
                  AND COALESCE(kind, 'news') = 'news'
            ) WHERE rn <= ? ORDER BY rn, published DESC LIMIT ?""",
        (site, since, *sections, *regions, ai.get("max_per_source", 60), ai.get("max_per_run", ai.get("max_per_call", 4000))),
    ).fetchall()
    out = {r["id"]: dict(r) for r in rows}
    for k in range(0, len(retry or []), 500):
        chunk = retry[k:k + 500]
        for r in conn.execute(f"SELECT * FROM articles WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            out.setdefault(r["id"], dict(r))
    arts = sorted(out.values(), key=lambda a: a["published"], reverse=True)
    for a in arts:
        a["publisher"] = publisher(a["outlet"])
        a["group"] = group_of(a, site_cfg)
    return arts


# ── Step 2: group the headlines (code) and pack them into AI calls ─────────────

def pick_shown(items: list[dict], k: int) -> tuple[list[dict], list[dict]]:
    """
    Which of a group's articles the AI sees: one per outlet first (wire and international outlets,
    then English), then more. The rest are added to the story by code if they match closely.
    """
    order = sorted(items, key=lambda a: (a.get("type") not in ("wire", "international"),
                                         (a.get("lang") or "en") != "en", a.get("published") or ""))
    first, seen = [], set()
    for a in order:
        if a["publisher"] not in seen:
            seen.add(a["publisher"])
            first.append(a)
    rest = [a for a in order if a not in first]
    shown = (first + rest)[:k]
    return shown, [a for a in items if a not in shown]


def is_promo(title: str, words: list[str], source: str = "") -> bool:
    """
    Product news and marketing from a vendor's blog ("Introducing...", "...acquires...", or a headline
    that starts with the vendor's own name, "CrowdStrike Extends..."): never a story on its own.
    """
    t = " " + re.sub(r"[^a-z0-9]+", " ", (title or "").lower()) + " "
    vendor = re.sub(r"[^a-z0-9]+", " ", source.lower()).split()[:1]
    return any(f" {w.lower()} " in t for w in words) or bool(vendor and t.startswith(f" {vendor[0]} "))


def make_batches(articles: list[dict], stories: list[dict], site: str, ai: dict,
                 solo: set[str] | frozenset = frozenset(), promo: list[str] | None = None) -> tuple[list[dict], dict]:
    """
    Cluster the articles (cluster.py), find which tracked story each group probably continues,
    and pack the groups into AI calls. Returns (batches, coverage numbers).

    A group goes to the AI if two or more outlets reported it, if it continues a tracked story,
    or if it holds research from a source listed in site.yaml's single_source_stories (a major
    lab's report is news on its own). Biggest first. Groups that don't fit wait for the next run.
    """
    idx = cluster.index_for(articles)
    groups = cluster.cluster(articles, site, idx)
    tracked = cluster.Stories(stories, idx, site)
    candidates = []
    for items in groups:
        outlets = len({a["publisher"] for a in items})
        hint, hits = tracked.match(items)
        research = next((a for a in items if a.get("source") in solo and not is_promo(a["title"], promo or [], a["source"])),
                        None) if outlets < 2 else None
        if outlets >= 2 or hint or research:
            candidates.append({"items": items, "outlets": outlets, "hint": hint,
                               "research": research["outlet"] if research and not hint else None})
    candidates.sort(key=lambda c: (-c["outlets"], -len(c["items"])))
    per_group, per_call = ai.get("group_articles", 10), ai.get("batch_articles", 300)
    max_groups, max_calls = ai.get("batch_groups", 40), ai.get("max_calls", 8)
    batches, current, size = [], [], 0
    for c in candidates:
        c["shown"], c["extra"] = pick_shown(c["items"], per_group)
        if current and (size + len(c["shown"]) > per_call or len(current) >= max_groups):
            batches.append(current)
            current, size = [], 0
        current.append(c)
        size += len(c["shown"])
    if current:
        batches.append(current)
    sent, waiting = batches[:max_calls], batches[max_calls:]
    out = []
    for groups_in_call in sent:
        wanted = {id(c["hint"]): c["hint"] for c in groups_in_call if c["hint"]}
        out.append({"groups": groups_in_call, "stories": list(wanted.values()), "idx": idx})
    coverage = {
        "articles": len(articles), "groups": len(groups),
        "reported_by_2": sum(1 for g in groups if len({a["publisher"] for a in g}) >= 2),
        "candidates": len(candidates), "continuing": sum(1 for c in candidates if c["hint"]),
        "sent": sum(len(b) for b in sent), "calls": len(sent),
        "waiting": sum(len(b) for b in waiting),
    }
    retry = [a["id"] for b in waiting for c in b for a in c["items"]][:RETRY_MAX]
    return out, coverage | {"retry": retry}


def strip_links(text: str) -> str:
    """'[Reuters](https://...) reported' -> 'Reuters reported'."""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text or "")


def build_prompt(site_cfg: dict, batch: dict, today: str):
    """
    The prompt for one AI call: the tracked stories its groups may continue (A), and the groups (B).
    Fills batch["refs"] ({number: article}) and each group's "nums" for apply_result.
    """
    template = (CONFIG / "prompts" / "narratives.md").read_text(encoding="utf-8")
    system_part, prompt_part = template.split("# PROMPT", 1)
    system_part = system_part.replace("# SYSTEM", "", 1).strip()

    names = {g["id"]: g["name"] for g in site_cfg["groups"]}
    existing_txt = "\n\n".join(
        f"id: {n['id']}\nsection: {names.get(n['group'], n['group'])}\ntitle: {n.get('label') or n['title']}\n"
        + (f"latest headline: {n['title']}\n" if n.get("label") and n["title"] != n["label"] else "")
        + f"last reported: {n['last_updated']}\n"
        + "".join(f"already reported (context only, don't copy this format): {strip_links(r['text'])}\n"
                  for r in n["reports"][:3])
        for n in batch["stories"]
    ) or "(none of the tracked stories matches these groups)"

    lines, refs, k = [], {}, 0
    for gi, c in enumerate(batch["groups"], start=1):
        lines.append(f"\n### Group {gi}" + (f" · continues: {c['hint']['id']}" if c["hint"] else "")
                     + (f" · research by {c['research']}: can be a story on its own" if c.get("research") else ""))
        c["nums"] = []
        for a in c["shown"]:
            k += 1
            refs[k] = a
            c["nums"].append(k)
            kind = a.get("type") or a.get("section") or ""
            summ = " ".join((a.get("summary") or "").split())[:160]
            lines.append(f"[{k}] {a['outlet']} ({kind}, {a.get('lang') or 'en'}) | {a['title']}" + (f" | {summ}" if summ else ""))
    batch["refs"] = refs

    values = {
        "site_name": site_cfg["name"], "date": today,
        "focus": site_cfg.get("focus", ""), "ignore": site_cfg.get("ignore", ""), "topics": ", ".join(TOPICS),
        "existing": existing_txt, "articles": "\n".join(lines).strip(), "article_count": len(refs),
        "group_count": len(batch["groups"]),
    }
    return Template(system_part).safe_substitute(values), Template(prompt_part).safe_substitute(values).strip()


# ── Step 4: check and keep the books ────────────────────────────────────────

def cite(text: str, refs: dict[int, dict]) -> str:
    """
    Turn the AI's '[3]' into a real link: '[Outlet](https://...)'. The AI never writes
    a URL, so it can't invent one. One link per outlet; trailing citations go in brackets.
    """
    def repl(m):
        links = {}
        for n in re.findall(r"\d+", m.group(0)):
            a = refs.get(int(n))
            name = publisher(a["outlet"]) if a else None
            if a and name not in links:                     # one link per publisher
                links[name] = f"[{name}]({a['url']})"
        if not links:
            return ""
        joined = ", ".join(links.values())
        trailing = re.match(r"\s*([.;:,]|$)", m.string[m.end():])
        part_of_sentence = re.search(r"\b(by|to|from|per|via|in|of|with|and)\s*$", m.string[:m.start()], re.I)
        return f"({joined})" if trailing and m.start() > 0 and not part_of_sentence else joined

    pattern = re.compile(r"\[\d+(?:\s*,\s*\d+)*\](?:\s*\[\d+(?:\s*,\s*\d+)*\])*")
    out = pattern.sub(repl, text or "")
    return re.sub(r"\s{2,}", " ", re.sub(r"\s+([.,;:])", r"\1", out)).strip()


def slugify(title: str, taken: set[str]) -> str:
    base = "-".join(re.sub(r"[^a-z0-9]+", " ", guardrails.plain(title)).split()[:6])[:50] or "story"
    slug, k = base, 2
    while slug in taken:
        slug, k = f"{base}-{k}", k + 1
    return slug


def checked_title(title: str, arts: list[dict]) -> tuple[str, str]:
    """
    A new story's title must be a neutral label built from the articles' own names.
    If it fails, use a real headline instead (from a wire or international outlet if possible).
    Returns (title, reason it was replaced or "").
    """
    title = " ".join((title or "").split()[:10]).strip(" .")
    probe = f"[1] reported {title}"              # reuse the sentence checks on the title
    ok, why = guardrails.check(probe, arts)
    if title and ok:
        return title, ""
    best = sorted(arts, key=lambda a: a.get("type") not in ("wire", "international"))[0]
    return best["title"][:100], why or "empty title"


def repair_citation(text: str, candidates: list[int], refs: dict[int, dict]) -> tuple[str, list[int]]:
    """
    In practice the AI often wrote "Outlet X reported ..."
    instead of "[12] reported ...". If the sentence NAMES an outlet, and that outlet really is
    the source of one of the articles the AI pointed to, put the [number] in for it.
    If the named outlet isn't one of those articles' outlets, nothing is repaired and the
    sentence is still rejected as uncited. The guardrails then check it as usual.
    """
    for k in candidates:
        outlet = refs[k]["outlet"]
        short = re.sub(r"\s*\([^)]*\)$", "", outlet)               # "Dawn (Pakistan)" -> "Dawn"
        pub = publisher(outlet)                                      # "The Guardian World" -> "The Guardian"
        for name in dict.fromkeys([outlet, short, pub, re.sub(r"^The\s+", "", outlet),
                                   re.sub(r"^The\s+", "", short), re.sub(r"^The\s+", "", pub)]):
            flags = 0 if len(name) < 4 else re.I                    # "RT" must match exactly, in capitals
            m = re.search(rf"(?<!\w)(?:[Tt]he\s+)?{re.escape(name)}(?!\w)", text, flags)
            if m and len(name) >= 2:
                same = [j for j in candidates if publisher(refs[j]["outlet"]) == pub]   # all its articles here
                return text[:m.start()] + "".join(f"[{j}]" for j in same) + text[m.end():], same
    return text, []


def is_duplicate(title: str, arts: list[dict], existing: dict, site: str) -> bool:
    """Is this "new" story really one we already track? Words AND places must agree."""
    a, b = story_words(title, arts), story_words(existing["title"], existing["articles"])
    if len(a) < MIN_WORDS or len(b) < MIN_WORDS or len(a & b) < MIN_SHARED or overlap(a, b) < SAME_STORY:
        return False
    g = gazetteer.load(site)
    if g:
        ca = set(g.score([x["title"] for x in arts], title))
        cb = set(g.score([x["title"] for x in existing["articles"][:12]], existing["title"]))
        if ca and cb and not ca & cb:          # no country in common: never the same story
            return False
    return True


def apply_corrections(state: dict, site: str, today: str, audit: list[dict]) -> list[str]:
    """
    Your manual fixes, from config/<site>/corrections.yaml, applied on every run.
    "remove_country"   takes everything about one country OUT of a story it was wrongly mixed into:
                       articles and reports that mention that country and none of the countries in the story's title.
    "remove_headline"  takes one headline (and any report resting only on it) out of a story. If the
                       story's title was that headline, the title goes back to the one before.
    "merge"            merges stories into the first one named.
    "hide"             takes a story off the site (it is archived, marked hidden).
    A story is named by its id, its title or its wider-story name.
    """
    path = CONFIG / site / "corrections.yaml"
    if not path.exists():
        return []
    from config import load_yaml
    rules = load_yaml(path) or {}
    g = gazetteer.load(site)
    done = []

    def find(want):
        want = str(want or "").strip().lower()
        return next((n for n in state["narratives"]
                     if want and want in (n["id"].lower(), n["title"].lower(), (n.get("label") or "").lower())), None)

    for rule in rules.get("remove_headline") or []:
        n, text = find(rule.get("story")), str(rule.get("headline") or "").strip().lower()
        if not n or not text:
            continue
        gone = {a["id"] for a in n["articles"] if text in a["title"].lower()}
        reps = [r for r in n["reports"] if not (r.get("articles") and set(r["articles"]) <= gone)]
        retitle = text in n["title"].lower()
        if not gone and not retitle:
            continue
        removed = len(gone)
        n["articles"] = [a for a in n["articles"] if a["id"] not in gone]
        n["article_count"] = max(len(n["articles"]), n.get("article_count", 0) - removed)
        dropped_reports, n["reports"] = len(n["reports"]) - len(reps), reps
        if retitle:
            earlier = [t for t in n.get("previous_titles") or [] if text not in t.lower()]
            n["title"] = earlier[-1] if earlier else n.get("label") or n["title"]
            n["previous_titles"] = earlier[:-1]
            n.pop("title_from", None)
        note(audit, "correction", today, n["group"], n["title"], rule.get("headline", ""),
             f"manual correction: headline removed ({removed} article(s), {dropped_reports} report(s))"
             + (", title restored" if retitle else ""))
        done.append(f"{n['title']}: removed '{rule.get('headline')}'")

    for rule in rules.get("merge") or []:
        names = rule.get("stories") or []
        keep = find(names[0]) if names else None
        for other in (find(x) for x in names[1:]):
            if keep and other and other is not keep:
                absorb(keep, other)
                state["narratives"].remove(other)
                note(audit, "correction", today, keep["group"], keep["title"], other["title"], "manual correction: merged")
                done.append(f"{other['title']} -> {keep['title']}")

    for rule in rules.get("hide") or []:
        n = find(rule.get("story") if isinstance(rule, dict) else rule)
        if n:
            state["narratives"].remove(n)
            state["archived"].insert(0, {k: n.get(k) for k in ("id", "group", "title", "first_seen", "last_updated", "article_count")}
                                     | {"hidden": True})
            note(audit, "correction", today, n["group"], n["title"], "", "manual correction: story hidden")
            done.append(f"{n['title']}: hidden")

    if not g:
        return done
    for rule in rules.get("remove_country") or []:
        want, country = str(rule.get("story", "")).strip().lower(), str(rule.get("country", "")).strip().lower()
        n = find(want)
        if not n or country not in g.countries:
            continue
        home = {c for c, w in g.find(f"{n.get('label') or ''} {n['title']}").items() if w >= 1} - {country}
        def about_it(text):
            found = {c for c, w in g.find(text).items() if w >= 1}
            return country in found and not found & home
        arts = [a for a in n["articles"] if not about_it(a["title"])]
        reps = [r for r in n["reports"] if not about_it(strip_links(r["text"]))]
        gone = len(n["articles"]) - len(arts) + len(n["reports"]) - len(reps)
        if gone:
            n["article_count"] = max(len(arts), n["article_count"] - (len(n["articles"]) - len(arts)))
            n["articles"], n["reports"] = arts, reps
            name = g.countries[country]["name"]
            note(audit, "correction", today, n["group"], n["title"], "", f"manual correction: removed {gone} items about {name}")
            done.append(f"{n['title']}: removed {gone} items about {name}")
    return done


def article_record(a: dict, today: str) -> dict:
    rec = {k: a.get(k) for k in ("id", "title", "outlet", "url", "published", "type", "lang", "section", "region")}
    rec["added"] = today
    rec["publisher"] = publisher(a["outlet"])
    found = dates_in(f"{a.get('title', '')} {(a.get('summary') or '')[:300]}", a.get("published") or "")
    if found:
        rec["dates"] = found                      # dates the article itself mentions (mentioned_dates.py)
    return rec


ATTRIBUTION = {"reported", "report", "said", "say", "says", "according", "stated", "cited", "citing", "quoted",
               "told", "announced", "claimed", "outlet", "state-run", "state", "wrote", "added", "that"}


def same_facts(new_text: str, old: dict, refs_outlets: set[str]) -> bool:
    """
    Does a new report only repeat an earlier one? Then it's corroboration, not news.
    The new sentence must add (almost) nothing: at least SAME_FACTS of its words are in the old one
    (outlet names and reporting verbs aside), and every number and name in it is already there.
    """
    new_plain, old_plain = guardrails.CITE.sub(" ", new_text), strip_links(old["text"])
    outlet_words = {w for o in refs_outlets | set(old.get("outlets", [])) for w in words(o)}
    a = {w for w in words(new_plain) if w not in ATTRIBUTION} - outlet_words
    b = {w for w in words(old_plain) if w not in ATTRIBUTION} - outlet_words
    if not a or len(a & b) / len(a) < SAME_FACTS:
        return False
    if not guardrails.numbers_in(new_plain) <= guardrails.numbers_in(old_plain):
        return False
    outlet_names = {w for o in refs_outlets | set(old.get("outlets", [])) for w in o.split()}
    return not (guardrails.names_in(new_plain) - guardrails.names_in(old_plain) - outlet_names)


def subject_hint(site: str, name: str, arts: list[dict]) -> str | None:
    """
    The AI's "country" for a story, accepted only if it is a country we know AND the story's
    own headlines name it. Otherwise ignored (and nothing else depends on it).
    """
    g = gazetteer.load(site)
    if not g or not (name or "").strip():
        return None
    cid = g.lookup(name.strip()) or next((c for c, w in g.find(name).items() if w >= 1), None)
    if not cid:
        return None
    scores = g.score([f"{a['title']} {(a.get('summary') or '')[:300]}" for a in arts])
    return cid if scores.get(cid) else None


def home_group(site: str, site_cfg: dict, title: str, arts: list[dict], hint: str | None) -> str:
    """
    Which group a NEW story is filed under. Geo: the region it is about (countries.py), so a story
    found in several regions' feeds at once is filed once. Otherwise the group most of its articles came from.
    """
    groups = {g["id"] for g in site_cfg["groups"]}
    g = gazetteer.load(site)
    if g:
        p = g.place(g.score([a["title"] for a in arts], title), "global", title, hint,
                    Counter(a.get("region") for a in arts if a.get("region")))
        if p["region"] in groups:
            return p["region"]
    most = Counter(a.get("group") for a in arts).most_common(1)
    return most[0][0] if most and most[0][0] in groups else site_cfg["groups"][-1]["id"]


def apply_result(state: dict, site_cfg: dict, batch: dict, result: dict, today: str,
                 run_touched: set[str], audit: list[dict]) -> Counter:
    site = state.get("site", "")
    refs = batch["refs"]
    index = {n["id"]: n for n in state["narratives"]}
    taken = set(index) | {n["id"] for n in state["archived"]}
    touched = set()
    counts = Counter()
    placed: dict[int, dict] = {}                     # article number -> story it went into

    story_group = ""

    def reject(story, text, reason):
        note(audit, "rejected", today, story_group, story, text, reason)
        counts["rejected"] += 1
        counts["why: " + reason.split(":")[0]] += 1

    def skip(story, reason):
        note(audit, "skipped", today, story_group, story, "", reason)
        counts["skipped"] += 1

    # Which tracked story code suggested for each article number ("continues: <id>" in the prompt)
    suggested = {k: c["hint"]["id"] for c in batch["groups"] if c.get("hint") for k in c.get("nums", [])}
    group_no = {k: gi for gi, c in enumerate(batch["groups"]) for k in c.get("nums", [])}
    idx = batch.get("idx")
    considered: set[int] = set()                     # every article number the AI put in any story
    keep_topics = set(site_cfg.get("topics") or [])

    for item in result.get("narratives", []):
        if not isinstance(item, dict):
            continue
        nums = [k for k in dict.fromkeys(item.get("articles") or []) if isinstance(k, int) and k in refs]
        considered.update(nums)
        n = index.get(item.get("id") or "")
        hint = subject_hint(site, item.get("country", ""), [refs[k] for k in nums])
        story_group = n["group"] if n else home_group(site, site_cfg, item.get("title", ""), [refs[k] for k in nums], hint)
        not_here: set[int] = set()                   # articles code took out of this continuation

        # The AI says "this continues story X". Each code group in its answer is checked on its own:
        # a group code suggested for X is fine; any other group's headlines must back it up
        # (cluster.related). Checking the answer as a whole let one unrelated headline ride along
        # with a correct group ("FSB foils terror plot in Stavropol" filed under the RAF Fairford plot).
        if n is not None and idx is not None and nums:
            by_group: dict[int, list[int]] = {}
            for k in nums:
                by_group.setdefault(group_no.get(k, -1), []).append(k)
            for gi, ks in by_group.items():
                if any(suggested.get(k) == n["id"] for k in ks) or cluster.related(idx, [refs[k] for k in ks], n, site):
                    continue
                not_here.update(ks)
            if not_here and len(not_here) < len(nums):
                for k in sorted(not_here):
                    skip(n["title"], f"not added to this story (headline doesn't match it): {refs[k]['title'][:80]}")
                nums = [k for k in nums if k not in not_here]
            elif not_here:
                skip(n["title"], f"continuation not supported by the headlines: {refs[nums[0]]['title'][:80]}")
                not_here = set()
                n = None
                item = dict(item, id="", title="")   # its title was the old story's: a new one comes from its headlines
                story_group = home_group(site, site_cfg, "", [refs[k] for k in nums], hint)

        # Rule 4, enforced in code: a new story needs two articles, unless its one article is
        # research from a source in single_source_stories (site.yaml).
        solo = (len(nums) == 1 and refs[nums[0]].get("source") in set(site_cfg.get("single_source_stories") or [])
                and not is_promo(refs[nums[0]]["title"], site_cfg.get("single_source_skip") or [], refs[nums[0]].get("source") or ""))
        if n is None and len(nums) < 2 and not solo:
            if nums:
                skip(item.get("title", ""), "new story with fewer than 2 articles")
            continue

        if n is None and content.offtopic_story(item.get("title", ""), [refs[k]["title"] for k in nums], site):
            skip(item.get("title", ""), "off-topic for this site (entertainment, sport...): not created")
            continue

        # The AI's topic (rule 13), checked against the site's list. A missing topic doesn't drop
        # a story: the other filters still apply, and losing real news is worse than one stray story.
        topic = str(item.get("topic") or "").strip().lower()
        if n is None and keep_topics and topic and topic not in keep_topics:
            skip(item.get("title", ""), f"off-topic for this site (topic: {topic}): not created")
            continue

        if n is None:   # the AI says "new story": first check it isn't one we already track
            fresh = story_words(item.get("title", ""), [refs[k] for k in nums])
            best = max(state["narratives"], default=None,
                       key=lambda e: overlap(fresh, story_words(e["title"], e["articles"])))
            if best and is_duplicate(item.get("title", ""), [refs[k] for k in nums], best, site):
                n = best
                counts["merged"] += 1
                note(audit, "merged", today, best["group"], best["title"], item.get("title", ""),
                     "duplicate story merged into an existing one")

        if n is None:                                          # brand-new story
            title, why = checked_title(item.get("title", ""), [refs[k] for k in nums])
            if why:
                note(audit, "title", today, story_group, title, item.get("title", ""), f"title replaced by a headline: {why}")
            # "label" names the wider story and stays; "title" becomes each day's lead headline (finalize)
            n = {"id": slugify(title, taken), "group": story_group, "title": title, "label": title,
                 "first_seen": today, "articles": [], "article_count": 0, "reports": []}
            if topic in TOPICS:
                n["topic"] = topic
            taken.add(n["id"])
            state["narratives"].append(n)
            index[n["id"]] = n
            counts["new"] += 1
        if hint and not n.get("subject"):
            n["subject"] = hint                                # checked: named in its own headlines

        new_reports, corroborated = [], False
        if not item.get("reports") and n["first_seen"] == today and not n["reports"]:
            note(audit, "info", today, n["group"], n["title"], "", "new story returned without any report (headlines still shown)")
        for r in item.get("reports") or []:
            if not isinstance(r, dict):
                continue
            text = (r.get("text") or "").strip()
            cited = [int(k) for k in re.findall(r"\d+", " ".join(guardrails.CITE.findall(text)))]
            if not cited:   # named the outlet instead of writing [n]? (see repair_citation)
                pointed = [k for k in r.get("articles") or [] if isinstance(k, int) and k in refs] or nums
                text, cited = repair_citation(text, pointed, refs)
                counts["repaired"] += bool(cited)
            if any(k not in refs for k in cited):
                reject(n["title"], text, "cites an article number that doesn't exist")
                continue
            if any(k in not_here for k in cited):
                reject(n["title"], text, "cites an article that doesn't belong to this story")
                continue
            ok, why = guardrails.check(text, [refs[k] for k in cited])
            if not ok:
                reject(n["title"], text, why)
                continue
            ids = sorted({refs[k]["id"] for k in cited})
            outlets = list(dict.fromkeys(publisher(refs[k]["outlet"]) for k in cited))
            mine = words(cite(text, refs))
            nums += [k for k in cited if k not in nums]        # a cited article belongs to the story
            # Same articles already cited today, or near-identical wording from the same outlets: nothing new.
            def known_outlets(old):
                return set(old.get("outlets", [])) | {x["outlet"] for x in old.get("also", [])}
            if any(((old["date"] == today and old["articles"] == ids) or overlap(mine, words(old["text"])) >= SAME_REPORT)
                   and set(outlets) <= known_outlets(old) for old in n["reports"] + new_reports):
                counts["duplicate reports"] += 1
                continue
            # The same facts from another outlet: corroboration ("also reported by"), not a new report.
            same = next((old for old in new_reports + n["reports"] if same_facts(text, old, set(outlets))), None)
            if same:
                have = set(same.get("outlets", [])) | {x["outlet"] for x in same.get("also", [])}
                added_outlet = False
                for k in cited:
                    pub = publisher(refs[k]["outlet"])
                    if pub not in have:
                        have.add(pub)
                        same.setdefault("also", []).append({"outlet": pub, "url": refs[k]["url"],
                                                            "published": refs[k]["published"], "date": today})
                        added_outlet = corroborated = True
                counts["corroborated" if added_outlet else "duplicate reports"] += 1
                continue
            new_reports.append({"date": today, "group": n["group"], "text": cite(text, refs), "articles": ids,
                                "outlets": outlets, "published": min(refs[k]["published"] for k in cited)})
            counts["kept"] += 1

        for k in nums:
            placed[k] = n
        known = {a["id"] for a in n["articles"]}
        added = [article_record(refs[k], today) for k in nums if refs[k]["id"] not in known]
        if not added and not new_reports and not corroborated:
            continue                     # nothing new for an existing story: leave it as it was
        add_to_story(n, added, new_reports, today)
        if new_reports:
            n["last_reported"] = today
        touched.add(n["id"])
        run_touched.add(n["id"])

    # Articles of a group the AI didn't see (only 10 per group are shown): added by code to the
    # story that got most of the group, if each one passes the grouping test with an article the
    # AI placed there. Never used for reports, only listed as coverage.
    for c in batch["groups"]:
        homes = Counter(id(placed[k]) for k in c.get("nums", []) if k in placed)
        if not homes or not c.get("extra") or not idx:
            continue
        top, hits = homes.most_common(1)[0]
        if hits * 2 < len(c["nums"]):
            continue
        n = next(placed[k] for k in c["nums"] if k in placed and id(placed[k]) == top)
        mates = [refs[k] for k in c["nums"] if placed.get(k) is n]
        known = {a["id"] for a in n["articles"]}
        extra = [article_record(a, today) for a in c["extra"]
                 if a["id"] not in known and any(cluster.close(idx, a, m) for m in mates)]
        if extra:
            add_to_story(n, extra, [], today)
            counts["attached by code"] += len(extra)
            touched.add(n["id"])
            run_touched.add(n["id"])
    # Groups of 2+ outlets the AI said nothing about: logged, so "why isn't X on the site?" has an
    # answer in the audit (usually: the AI judged it off-topic for this site).
    for c in batch["groups"]:
        if c.get("outlets", 0) >= 2 and c.get("nums") and not considered & set(c["nums"]):
            note(audit, "dropped", today, c["items"][0].get("group", ""), "", refs[c["nums"][0]]["title"],
                 f"the AI returned no story for this group of {c['outlets']} outlets (judged off-topic or not news)")
            counts["dropped"] += 1
    counts["in stories"] += len(placed)
    counts["updated"] = sum(1 for i in touched if index[i]["first_seen"] != today)
    counts["ids"] = touched
    return counts


def add_to_story(n: dict, added: list[dict], new_reports: list[dict], today: str):
    n["articles"] = sorted(added + n["articles"], key=lambda a: a["published"], reverse=True)[:KEEP_ARTICLES]
    n["article_count"] = n.get("article_count", 0) + len(added)
    n["reports"] = (new_reports + n["reports"])[:KEEP_REPORTS]
    n["last_updated"] = today


def merge_duplicates(state: dict, site: str, today: str, audit: list[dict], idx) -> list[str]:
    """
    After all calls: two tracked stories that turn out to be the same event (the AI started a
    second one in another call) are merged into the older one. Same test as the grouping, on
    their headlines, and never across countries.
    """
    g = gazetteer.load(site)
    recent = (datetime.fromisoformat(today) - timedelta(days=2)).date().isoformat()
    live = [n for n in state["narratives"] if n["last_updated"] >= recent]
    live.sort(key=lambda n: (n["first_seen"], -n.get("article_count", 0)))      # oldest first: they absorb
    heads = {n["id"]: cluster.story_heads(n, 15) for n in live}
    where = {n["id"]: (set(g.score([t for t, _ in heads[n["id"]][1:]], n["title"])) if g else set()) for n in live}
    done, gone = [], set()
    for i, keep in enumerate(live):
        if keep["id"] in gone:
            continue
        for other in live[i + 1:]:
            if other["id"] in gone or today not in (keep["last_updated"], other["last_updated"]):
                continue
            if where[keep["id"]] and where[other["id"]] and not where[keep["id"]] & where[other["id"]]:
                continue
            if cluster.same_story_share(idx, heads[keep["id"]], heads[other["id"]]) < MERGE_SHARE:
                continue
            absorb(keep, other)
            gone.add(other["id"])
            note(audit, "merged", today, keep["group"], keep["title"], other["title"], "duplicate story merged into an existing one")
            done.append(f"{other['title']} -> {keep['title']}")
    state["narratives"] = [n for n in state["narratives"] if n["id"] not in gone]
    return done


def absorb(keep: dict, other: dict):
    """Move another story's articles and reports into `keep` (the older story keeps its id and names)."""
    known = {a["id"] for a in keep["articles"]}
    moved = [a for a in other["articles"] if a["id"] not in known]
    keep["articles"] = sorted(moved + keep["articles"], key=lambda a: a["published"], reverse=True)[:KEEP_ARTICLES]
    keep["article_count"] = keep.get("article_count", 0) + len(moved)
    keep["reports"] = sorted(other["reports"] + keep["reports"], key=lambda r: r["date"], reverse=True)[:KEEP_REPORTS]
    keep["last_updated"] = max(keep["last_updated"], other["last_updated"])
    keep["last_reported"] = max(keep.get("last_reported") or "", other.get("last_reported") or "") or None
    keep.setdefault("merged", []).append(other["id"])


# ── Duplicates the word test can't see: code suspects, the AI confirms ──────────

DUP_SCHEMA = {"type": "object", "properties": {"pairs": {"type": "array", "items": {"type": "object", "properties": {
    "pair": {"type": "integer"}, "same": {"type": "boolean"}}, "required": ["pair", "same"]}}}, "required": ["pairs"]}


def duplicate_candidates(state: dict, site: str, today: str, idx) -> list[tuple[dict, dict]]:
    """
    Pairs of stories updated today, at least one of them started today, whose countries don't clash
    and whose CORE names overlap. The word test misses these on a big day: when everyone writes
    "Microsoft", the word stops being rare, and a Spanish and a French headline share little else.

    A story's core names: rare capitalised words (not countries) in its wider-story name, or in at
    least two of today's headlines. Names found in more than DUP_COMMON stories (Trump, Putin on a
    busy day) don't count. Pairs are ranked by overlap relative to their size (shared / sqrt(a * b)),
    so a long-running story with dozens of names doesn't crowd out the real duplicates.
    """
    g = gazetteer.load(site)
    live = [n for n in state["narratives"] if n["last_updated"] == today]
    places = cluster.place_tokens()
    core, where = {}, {}
    for n in live:
        arts = [a for a in n["articles"] if a.get("added") == today][:10] or n["articles"][:8]
        seen = Counter(w for a in arts for w in cluster.features(idx, a["title"], a.get("lang"))[1] - places)
        label = cluster.features(idx, n.get("label") or n["title"], "en")[1] - places
        core[n["id"]] = label | {w for w, k in seen.items() if k >= 2 or len(arts) <= 2}
        where[n["id"]] = set(g.score([a["title"] for a in arts], n.get("label") or n["title"])) if g else set()
    common = {w for w, k in Counter(w for s in core.values() for w in s).items() if k > DUP_COMMON}
    pairs = []
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if today not in (a["first_seen"], b["first_seen"]):
                continue
            if where[a["id"]] and where[b["id"]] and not where[a["id"]] & where[b["id"]]:
                continue
            na, nb = core[a["id"]] - common, core[b["id"]] - common
            shared = na & nb
            if shared and len(shared) / math.sqrt(len(na) * len(nb)) >= DUP_OVERLAP:
                pairs.append((len(shared) / math.sqrt(len(na) * len(nb)), a, b))
    pairs.sort(key=lambda p: -p[0])
    return [(a, b) for _, a, b in pairs[:DUP_PAIRS]]


def confirm_duplicates(state: dict, site: str, today: str, audit: list[dict], idx) -> list[str]:
    """
    One AI call: "do these two stories report the same event?" for each suspected pair. Code merges
    only the pairs it asked about and the AI answered yes for, into the older story.
    """
    pairs = duplicate_candidates(state, site, today, idx)
    if not pairs:
        return []
    template = (CONFIG / "prompts" / "duplicates.md").read_text(encoding="utf-8")
    system, prompt = (part.strip() for part in template.split("# PROMPT", 1))
    system = system.replace("# SYSTEM", "", 1).strip()

    def block(n):
        heads = [a["title"] for a in n["articles"][:4]]
        return f"{n.get('label') or n['title']}\n" + "".join(f"    - {h}\n" for h in heads)
    text = "\n".join(f"### Pair {i}\nA: {block(a)}B: {block(b)}" for i, (a, b) in enumerate(pairs, start=1))
    try:
        answer = ask_json(system, Template(prompt).safe_substitute(pairs=text, count=len(pairs)), DUP_SCHEMA)
    except LLMError as ex:
        print(f"  duplicate check failed ({ex}): no stories merged by it")
        return []
    same = {p.get("pair") for p in answer.get("pairs") or [] if p.get("same") is True}
    stories = {n["id"]: n for n in state["narratives"]}
    home: dict[str, str] = {}                        # merged story id -> the story it went into

    def root(i):
        while i in home:
            i = home[i]
        return i
    done = []
    for k, (a, b) in enumerate(pairs, start=1):
        if k not in same:
            continue
        ra, rb = root(a["id"]), root(b["id"])
        if ra == rb:
            continue
        keep, other = sorted((stories[ra], stories[rb]), key=lambda n: (n["first_seen"], -n.get("article_count", 0)))
        absorb(keep, other)
        home[other["id"]] = keep["id"]
        note(audit, "merged", today, keep["group"], keep["title"], other["title"],
             "same event, confirmed by the AI's duplicate check: merged into the older story")
        done.append(f"{other['title']} -> {keep['title']}")
    state["narratives"] = [n for n in state["narratives"] if n["id"] not in home]
    return done


def drop_commentary(conn, state: dict, site: str, today: str, audit: list[dict]) -> int:
    """
    Take opinion and analysis pieces out of every story, and remove any report that
    rests only on them. Stories built before 7b can contain them (the AI used to see op-eds too).
    The pieces aren't lost: the website shows them, labelled, under "Opinion and analysis".
    """
    removed = 0
    for n in state["narratives"]:
        kinds = content.kinds_by_id(conn, n["articles"], site)
        news, comment, keep, drop = content.split_story(n, kinds)
        if len(news) == len(n["articles"]) and not drop:
            continue
        for r in drop:
            note(audit, "commentary", today, n["group"], n["title"], strip_links(r["text"]),
                 "cited only opinion, analysis or off-topic pieces (not news reporting)")
        n["articles"], n["reports"] = news, keep
        n["article_count"] = max(len(news), n["article_count"] - len(comment))
        removed += len(drop)
    return removed


def status_of(n: dict, start: str) -> str:
    """
    new        first seen in the window
    updated    a new report (new facts) in the window
    covered    only more coverage: new articles, or outlets corroborating earlier reports
    unchanged  nothing in the window
    """
    last_reported = n.get("last_reported") or max((r["date"] for r in n.get("reports", [])), default="")
    return ("new" if n["first_seen"] >= start else "updated" if last_reported >= start
            else "covered" if n["last_updated"] >= start else "unchanged")


def lead_titles(state: dict, site: str, today: str, idx) -> int:
    """
    Each story's title becomes the day's lead headline: the real headline that matches the most
    other outlets' coverage of it today (cluster.lead_headline). Picked by code, never written by
    the AI, and never a one-off: without enough backing, yesterday's title stays. The wider-story
    name ("label") doesn't change, so the website can show "part of: <wider story>" above it.
    """
    changed = 0
    for n in state["narratives"]:
        todays = [a for a in n["articles"] if a.get("added") == today]
        best, backing, others = cluster.lead_headline(idx, todays, site)
        if not best or best["title"] == n["title"]:
            continue
        if n["title"] not in (n.get("label"), *(n.get("previous_titles") or [])):
            n["previous_titles"] = (n.get("previous_titles") or [])[-9:] + [n["title"]]
        n["title"] = best["title"]
        n["title_from"] = {"outlet": best.get("publisher") or publisher(best["outlet"]), "url": best["url"],
                           "date": today, "backing": backing, "of": others}
        changed += 1
    return changed


def finalize(state: dict, today: str):
    """Counted, not judged: how many outlets reported each story today, and sourcing flags."""
    # A story left with nothing to show (every article removed as commentary, say) is dropped.
    state["narratives"] = [n for n in state["narratives"] if n["articles"] or n["reports"]]
    for n in state["narratives"]:
        # Status comes from DATES, not from this run, so running twice in a day gives the same
        # result as running once (the second run used to mark the morning's stories "unchanged").
        n["status"] = status_of(n, today)
        todays = [a for a in n["articles"] if a.get("added") == today]
        outlets = {publisher(a["outlet"]) for a in todays}   # BBC World + BBC Africa = 1 outlet
        outlets |= {o for r in n["reports"] if r["date"] == today for o in r.get("outlets", [])}
        outlets |= {x["outlet"] for r in n["reports"] for x in r.get("also", []) if x.get("date") == today}
        n["articles_today"] = len(todays)
        n["outlets_today"] = len(outlets)
        n["single_source_today"] = len(outlets) == 1
        n["state_media_only_today"] = bool(todays) and all(a.get("type") == "state-media" for a in todays)


def save_coverage(state: dict, today: str, cov: dict, totals: Counter, failed: int, errors: list[str] | None = None):
    """
    Collection statistics per day (summed over runs), shown on the Overview's quality panel.
    errors: why AI calls failed (no keys or personal data can be in them: they come from the
    model's or the service's own error messages), so a failure can be diagnosed without the logs.
    """
    days = state.setdefault("coverage", [])
    day = next((d for d in days if d["date"] == today), None)
    if not day:
        day = {"date": today}
        days.insert(0, day)
    for k in ("articles", "groups", "reported_by_2", "candidates", "continuing", "sent", "calls", "waiting"):
        day[k] = day.get(k, 0) + cov.get(k, 0)
    for k in ("new", "updated", "kept", "rejected", "corroborated", "attached by code", "in stories", "merged",
              "skipped", "dropped", "split calls"):
        day[k.replace(" ", "_")] = day.get(k.replace(" ", "_"), 0) + totals.get(k, 0)
    day["failed_calls"] = day.get("failed_calls", 0) + failed
    day["runs"] = day.get("runs", 0) + 1
    if errors:
        day["errors"] = (day.get("errors", []) + [e[:200] for e in errors])[-5:]
    state["coverage"] = days[:COVERAGE_DAYS]


def expire(state: dict, site_cfg: dict, today: str) -> list[str]:
    cutoff = (datetime.fromisoformat(today) - timedelta(days=site_cfg.get("expire_days", 6))).date().isoformat()
    gone = [n for n in state["narratives"] if n["last_updated"] < cutoff]
    for n in gone:
        state["narratives"].remove(n)
        state["archived"].insert(0, {k: n[k] for k in ("id", "group", "title", "first_seen", "last_updated", "article_count")})
    state["archived"] = state["archived"][:KEEP_ARCHIVED]
    return [n["title"] for n in gone]


# ── Putting it together ─────────────────────────────────────────────────────

def split(batch: dict) -> list[dict]:
    """A batch of groups cut in two halves, each with the tracked stories its own groups may continue."""
    mid = len(batch["groups"]) // 2
    halves = []
    for part in (batch["groups"][:mid], batch["groups"][mid:]):
        hints = {c["hint"]["id"]: c["hint"] for c in part if c.get("hint")}
        halves.append({"groups": part, "stories": list(hints.values()), "idx": batch.get("idx")})
    return halves


def ask_batch(site_cfg: dict, batch: dict, today: str, ai: dict, label: str, depth: int = 0):
    """
    One AI call. If the answer was cut off, unreadable or blocked (LLMError.smaller), the groups are
    split in two and each half is tried once: a smaller answer usually fits.
    Returns ([(batch, answer)], [batches that failed], [why]).
    """
    system, prompt = build_prompt(site_cfg, batch, today)
    try:
        return [(batch, ask_json(system, prompt, SCHEMA))], [], []
    except LLMError as ex:
        why = f"{label}: {ex}"
        if getattr(ex, "smaller", False) and depth == 0 and len(batch["groups"]) >= 2:
            print(f"  {why} -> splitting it in two and trying each half")
            done, failed, errors = [], [], []
            for k, half in enumerate(split(batch)):
                time.sleep(ai.get("pause_seconds", 10))
                d, f, e = ask_batch(site_cfg, half, today, ai, f"{label}{'ab'[k]}", depth + 1)
                done, failed, errors = done + d, failed + f, errors + e
            return done, failed, errors
        print(f"  {why}")
        return [], [batch], [why]


def run_site(site: str, only_group: str | None, dry_run: bool):
    site_cfg, ai = load_site(site), load_ai()
    state = load_state(site)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    today = now.date().isoformat()
    conn = store.connect()
    if only_group and only_group not in {g["id"] for g in site_cfg["groups"]}:
        raise SystemExit(f"No group '{only_group}' in config/{site}/site.yaml")
    # One clock for the whole site. Older state files kept one per group: start from the earliest.
    last = state["last_run"]
    since = last.get("all") or min(last.values(), default=None) or (now - timedelta(hours=24)).isoformat()
    since = max(since, (now - timedelta(hours=48)).isoformat())   # after a long outage, the last 2 days only

    print(f"\n=== {site_cfg['name']} ({ai.get('provider')}: {ai.get('model')}) ===")
    articles = select_articles(conn, site, site_cfg, since, ai, only_group, state.get("retry"))
    batches, cov = make_batches(articles, state["narratives"], site, ai, set(site_cfg.get("single_source_stories") or []),
                                site_cfg.get("single_source_skip") or [])
    print(f"{len(articles)} new articles -> {cov['groups']} groups ({cov['reported_by_2']} reported by 2+ outlets); "
          f"{cov['candidates']} go to the AI ({cov['continuing']} continue a tracked story) in {len(batches)} call(s)"
          + (f"; {cov['waiting']} wait for the next run (max_calls)" if cov["waiting"] else ""))

    run_touched: set[str] = set()
    audit: list[dict] = []
    totals = Counter()
    failed, failed_calls, errors = [], 0, []
    for i, batch in enumerate(batches):
        if dry_run:
            system, prompt = build_prompt(site_cfg, batch, today)
            out = ROOT / "data" / "prompts" / f"{site}-{i + 1}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(f"=== SYSTEM ===\n{system}\n\n=== PROMPT ===\n{prompt}", encoding="utf-8")
            print(f"  call {i + 1}: {len(batch['groups'])} groups, {len(batch['refs'])} articles; prompt saved to "
                  f"{out.relative_to(ROOT)} (~{len(system + prompt) // 4:,} tokens)")
            continue
        if i > 0:
            time.sleep(ai.get("pause_seconds", 10))
        done, bad, why = ask_batch(site_cfg, batch, today, ai, f"call {i + 1}")
        totals["split calls"] += int(len(done) + len(bad) > 1)
        errors += why
        for b in bad:                                  # their articles are retried on the next run
            failed += [a["id"] for c in b["groups"] for a in c["items"]]
            failed_calls += 1
        for part, result in done:
            label = f"call {i + 1}" + (f" ({len(part['groups'])} of its groups)" if part is not batch else "")
            try:
                counts = apply_result(state, site_cfg, part, result, today, run_touched, audit)
            except Exception as ex:                    # one strange answer (or a bug) must not lose the whole run
                traceback.print_exc()
                errors.append(f"{label}: the answer could not be used ({type(ex).__name__})")
                failed += [a["id"] for c in part["groups"] for a in c["items"]]
                failed_calls += 1
                continue
            totals.update({k: v for k, v in counts.items() if k != "ids"})
            print(f"  {label}: {len(part['groups'])} groups, {len(part['refs'])} articles -> {counts['new']} new, "
                  f"{counts['updated']} updated stories; {counts['kept']} reports kept, {counts['rejected']} removed by guardrails"
                  + (f", {counts['corroborated']} corroborations" if counts["corroborated"] else "")
                  + (f", {counts['skipped']} proposals skipped" if counts["skipped"] else "")
                  + (f", {counts['dropped']} groups returned without a story" if counts["dropped"] else "")
                  + (f" ({counts['repaired']} citations added by code)" if counts["repaired"] else "")
                  + (f"; {counts['attached by code']} more articles added by code" if counts["attached by code"] else ""))

    if dry_run:
        conn.close()
        return
    merged = merge_duplicates(state, site, today, audit, batches[0]["idx"]) if batches else []
    if batches and len(failed) < sum(len(c["items"]) for b in batches for c in b["groups"]):
        time.sleep(ai.get("pause_seconds", 10))
        merged += confirm_duplicates(state, site, today, audit, batches[0]["idx"])
    totals["merged"] += len(merged)
    for line in merged:
        print(f"\nMerged duplicate story: {line}")
    for line in apply_corrections(state, site, today, audit):
        print(f"\nCorrection (config/{site}/corrections.yaml): {line}")
    dropped = drop_commentary(conn, state, site, today, audit)
    if dropped:
        print(f"\nRemoved {dropped} report(s) that rested only on opinion or analysis pieces")
    if batches:
        print(f"\n{lead_titles(state, site, today, batches[0]['idx'])} stories titled with today's lead headline")
    finalize(state, today)
    gone = expire(state, site_cfg, today)
    if gone:
        print(f"\nArchived (no reporting for {site_cfg.get('expire_days', 6)} days): " + "; ".join(gone))
    if batches and len(failed) == sum(len(c["items"]) for b in batches for c in b["groups"]):
        print("\nEvery AI call failed: the clock isn't moved, so the same articles are tried next run.")
    else:
        state["last_run"] = {"all": now.isoformat()}
        state["retry"] = (cov["retry"] + failed)[:RETRY_MAX]
    save_coverage(state, today, cov, totals, failed_calls, errors)
    names = {g["id"]: g["name"] for g in site_cfg["groups"]}
    for n in (n for n in state["narratives"] if n["id"] in run_touched):
        print(f"   [{n['status']:<9}] {n['title']}  ({names.get(n['group'], n['group'])})")
    save_state(site, state)
    save_audit(site, audit, today)
    why = ", ".join(f"{v} {k[5:]}" for k, v in totals.most_common() if k.startswith("why: "))
    print(f"\nGuardrails: {totals['kept']} reports kept, {totals['rejected']} removed" + (f" ({why})" if why else ""))
    print(f"Saved state/{site}/narratives.json ({len(state['narratives'])} stories) and state/{site}/audit.json")
    conn.close()


def show(site: str):
    state, site_cfg = load_state(site), load_site(site)
    print(f"\n=== {site_cfg['name']}: {len(state['narratives'])} stories ===")
    for g in site_cfg["groups"]:
        ns = sorted((n for n in state["narratives"] if n["group"] == g["id"]),
                    key=lambda n: (-n.get("outlets_today", 0), -n["article_count"]))
        if not ns:
            continue
        print(f"\n{g['name']}")
        for n in ns:
            flags = (" · single source" if n.get("single_source_today") else "") + \
                    (" · state media only" if n.get("state_media_only_today") else "")
            k = n.get("outlets_today", 0)
            print(f"  [{n['status']:<9}] {n['title']}  ({k} outlet{'' if k == 1 else 's'} today{flags})")
            for r in n["reports"]:
                if r["date"] == n["last_updated"]:
                    print(f"      - {strip_links(r['text'])}")


def show_audit(site: str):
    path = STATE / site / "audit.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    kinds = Counter(e.get("kind", "?") for e in entries)
    print(f"\n=== Audit ({site}, last {AUDIT_DAYS} days): {len(entries)} entries: "
          + ", ".join(f"{v} {k}" for k, v in kinds.most_common()) + " ===")
    for e in entries[-40:]:
        print(f"\n  {e['date']} · [{e.get('kind', '?')}] {e['story']}\n    \"{e['text']}\"\n    -> {e['reason']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Group articles into stories and collect attributed reports.")
    ap.add_argument("--site", choices=sites())
    ap.add_argument("--group", help="only this group id (e.g. europe)")
    ap.add_argument("--dry-run", action="store_true", help="build and save prompts without calling the AI")
    ap.add_argument("--show", action="store_true", help="print the stories currently tracked")
    ap.add_argument("--audit", action="store_true", help="print what the guardrails removed")
    a = ap.parse_args()
    for s in [a.site] if a.site else sites():
        if a.show:
            show(s)
        elif a.audit:
            show_audit(s)
        else:
            run_site(s, a.group, a.dry_run)
