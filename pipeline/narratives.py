"""
narratives.py - group the day's articles into stories, and collect what each outlet REPORTED.

Usage (from the repo folder):
  python pipeline/narratives.py                             # every site, every group
  python pipeline/narratives.py --site geo --group europe   # just one (saves free-tier quota)
  python pipeline/narratives.py --site geo --dry-run        # build the prompts, don't call the AI
  python pipeline/narratives.py --site geo --show           # print what's being tracked
  python pipeline/narratives.py --site geo --audit          # what the guardrails removed

This is a COLLECTION tool, not an analysis tool. The AI's job is narrow:
  - group articles into stories, and
  - write one-sentence REPORTS: "[12] reported that ..." (attributed, nothing added).

Everything else is plain code, and the code checks the AI's work:
  1. Reports must cite real articles; the AI writes [12], the code inserts the real link.
  2. Every report passes guardrails.py (attribution, numbers, names, no analysis words).
     Failures are removed and logged to state/<site>/audit.json.
  3. Story titles are checked too; a bad title is replaced by a real headline.
  4. Ranking is by how many different outlets reported a story today: counted, not judged.
  5. The website always shows the original headlines next to the AI's sentences.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from string import Template

import content
import countries as gazetteer
import guardrails
import store
from config import CONFIG, ROOT, load_ai, load_publishers, load_site, sites
from llm import LLMError, ask_json

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
                    "articles": {"type": "array", "items": {"type": "integer"}},
                    "reports": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"text": {"type": "string"},
                                           "articles": {"type": "array", "items": {"type": "integer"}}},
                            "required": ["text", "articles"],
                        },
                    },
                },
                "required": ["id", "title", "articles", "reports"],
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
    return state


def save_state(site: str, state: dict):
    path = STATE / site / "narratives.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def save_audit(site: str, entries: list[dict], today: str):
    """Everything the guardrails removed, kept for AUDIT_DAYS days. Read it with --audit."""
    path = STATE / site / "audit.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    cutoff = (datetime.fromisoformat(today) - timedelta(days=AUDIT_DAYS)).date().isoformat()
    keep = [e for e in old if e["date"] >= cutoff and e["date"] != today] + entries
    path.write_text(json.dumps(keep, indent=1, ensure_ascii=False), encoding="utf-8")


# ── Step 1: pick articles ───────────────────────────────────────────────────

def select_articles(conn, site: str, group: dict, since: str, ai: dict) -> list[dict]:
    """
    New articles for this group since the last run, at most N per source.

    Fair trimming: if there are more than max_per_call, we keep every source's newest article
    first, then every source's 2nd newest, and so on (ORDER BY rn). So the cap trims each source
    a little, instead of cutting off everything published before a certain hour.
    """
    field, values = ("section", group["sections"]) if group.get("sections") else ("region", [group["id"]])
    marks = ",".join("?" * len(values))
    # Only NEWS goes to the AI. Opinion and analysis (content.py) are never restated as fact.
    rows = conn.execute(
        f"""SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY source ORDER BY published DESC) AS rn
                FROM articles WHERE site = ? AND first_seen > ? AND {field} IN ({marks})
                  AND COALESCE(kind, 'news') = 'news'
            ) WHERE rn <= ? ORDER BY rn, published DESC LIMIT ?""",
        (site, since, *values, ai.get("max_per_source", 40), ai.get("max_per_call", 800)),
    ).fetchall()
    return sorted((dict(r) for r in rows), key=lambda a: a["published"], reverse=True)


# ── Step 2: build the prompt ────────────────────────────────────────────────

def strip_links(text: str) -> str:
    """'[Reuters](https://...) reported' -> 'Reuters reported'."""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text or "")


def build_prompt(site_cfg: dict, group: dict, existing: list[dict], articles: list[dict], today: str):
    template = (CONFIG / "prompts" / "narratives.md").read_text(encoding="utf-8")
    system_part, prompt_part = template.split("# PROMPT", 1)
    system_part = system_part.replace("# SYSTEM", "", 1).strip()

    names = {g["id"]: g["name"] for g in site_cfg["groups"]}
    shown = sorted(existing, key=lambda n: (n["group"] != group["id"], n["last_updated"]), reverse=False)[:80]
    existing_txt = "\n\n".join(
        f"id: {n['id']}\nsection: {names.get(n['group'], n['group'])}\ntitle: {n['title']}\n"
        f"last reported: {n['last_updated']}\n"
        + "".join(f"already reported (context only, don't copy this format): {strip_links(r['text'])}\n"
                  for r in n["reports"][:2])
        for n in shown
    ) or "(none yet: this is the first run)"

    lines = []
    for i, a in enumerate(articles, start=1):
        kind = a.get("type") or a.get("section") or ""
        summ = (a.get("summary") or "")[:160]
        lines.append(f"[{i}] {a['outlet']} ({kind}, {a.get('lang') or 'en'}) | {a['title']}" + (f" | {summ}" if summ else ""))

    values = {
        "site_name": site_cfg["name"], "group_name": group["name"], "date": today,
        "focus": site_cfg.get("focus", ""), "ignore": site_cfg.get("ignore", ""),
        "max_narratives": site_cfg.get("max_narratives", 10),
        "existing": existing_txt, "articles": "\n".join(lines), "article_count": len(articles),
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
    "remove_country" takes everything about one country OUT of a story it was wrongly mixed into:
    articles and reports that mention that country and none of the countries in the story's title.
    """
    path = CONFIG / site / "corrections.yaml"
    g = gazetteer.load(site)
    if not path.exists() or not g:
        return []
    from config import load_yaml
    done = []
    for rule in load_yaml(path).get("remove_country") or []:
        want, country = str(rule.get("story", "")).strip().lower(), str(rule.get("country", "")).strip().lower()
        n = next((n for n in state["narratives"] if want in (n["id"].lower(), n["title"].lower())), None)
        if not n or country not in g.countries:
            continue
        home = {c for c, w in g.find(n["title"]).items() if w >= 1} - {country}
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
            audit.append({"date": today, "group": n["group"], "story": n["title"], "text": "",
                          "reason": f"manual correction: removed {gone} items about {name}"})
            done.append(f"{n['title']}: removed {gone} items about {name}")
    return done


def article_record(a: dict, today: str) -> dict:
    rec = {k: a.get(k) for k in ("id", "title", "outlet", "url", "published", "type", "lang", "section")}
    rec["added"] = today
    rec["publisher"] = publisher(a["outlet"])
    return rec


def apply_result(state: dict, group: dict, result: dict, articles: list[dict], today: str,
                 run_touched: set[str], audit: list[dict]) -> dict:
    refs = {i: a for i, a in enumerate(articles, start=1)}
    index = {n["id"]: n for n in state["narratives"]}
    taken = set(index) | {n["id"] for n in state["archived"]}
    touched = set()
    counts = Counter()

    def reject(story, text, reason):
        audit.append({"date": today, "group": group["id"], "story": story, "text": text, "reason": reason})
        counts["rejected"] += 1
        counts["why: " + reason.split(":")[0]] += 1

    for item in result.get("narratives", []):
        nums = [k for k in dict.fromkeys(item.get("articles", [])) if k in refs]
        n = index.get(item.get("id") or "")

        if n is None and len(nums) < 2:                       # rule 3, enforced in code
            if nums:
                reject(item.get("title", ""), "", "new story with fewer than 2 articles")
            continue

        if n is None:   # the AI says "new story": first check it isn't one we already track
            fresh = story_words(item.get("title", ""), [refs[k] for k in nums])
            best = max(state["narratives"], default=None,
                       key=lambda e: overlap(fresh, story_words(e["title"], e["articles"])))
            if best and is_duplicate(item.get("title", ""), [refs[k] for k in nums], best, state.get("site", "")):
                n = best
                counts["merged"] += 1
                audit.append({"date": today, "group": group["id"], "story": best["title"], "text": item.get("title", ""),
                              "reason": "duplicate story merged into an existing one"})

        if n is None:                                          # brand-new story
            title, why = checked_title(item.get("title", ""), [refs[k] for k in nums])
            if why:
                reject(item.get("title", ""), item.get("title", ""), f"title replaced by a headline: {why}")
            n = {"id": slugify(title, taken), "group": group["id"], "title": title, "first_seen": today,
                 "articles": [], "article_count": 0, "reports": []}
            taken.add(n["id"])
            state["narratives"].append(n)
            index[n["id"]] = n
            counts["new"] += 1
        # Existing stories keep their title: a story's name stays the same day to day.

        new_reports = []
        if not item.get("reports"):   # logged so you can see it, but not counted as a removed sentence
            audit.append({"date": today, "group": group["id"], "story": n["title"], "text": "",
                          "reason": "story returned without any report (headlines still shown)"})
        for r in item.get("reports", []):
            text = (r.get("text") or "").strip()
            cited = [int(k) for k in re.findall(r"\d+", " ".join(guardrails.CITE.findall(text)))]
            if not cited:   # named the outlet instead of writing [n]? (see repair_citation)
                pointed = [k for k in r.get("articles", []) if k in refs] or nums
                text, cited = repair_citation(text, pointed, refs)
                counts["repaired"] += bool(cited)
            if any(k not in refs for k in cited):
                reject(n["title"], text, "cites an article number that doesn't exist")
                continue
            ok, why = guardrails.check(text, [refs[k] for k in cited])
            if not ok:
                reject(n["title"], text, why)
                continue
            ids = sorted({refs[k]["id"] for k in cited})
            mine = words(cite(text, refs))
            # Duplicate report: same articles cited today, or near-identical wording to ANY earlier
            # report in this story (any day). Repeating yesterday's fact isn't new reporting.
            duplicate = any((old["date"] == today and old["articles"] == ids) or
                            overlap(mine, words(old["text"])) >= SAME_REPORT
                            for old in n["reports"] + new_reports)
            if duplicate:
                counts["duplicate reports"] += 1
                continue
            new_reports.append({"date": today, "group": group["id"], "text": cite(text, refs), "articles": ids,
                                "outlets": list(dict.fromkeys(publisher(refs[k]["outlet"]) for k in cited))})
            nums += [k for k in cited if k not in nums]        # a cited article belongs to the story
            counts["kept"] += 1

        known = {a["id"] for a in n["articles"]}
        added = [article_record(refs[k], today) for k in nums if refs[k]["id"] not in known]
        if not added and not new_reports:
            continue                     # nothing new for an existing story: leave it as it was
        if n["first_seen"] != today and n["id"] not in touched:
            counts["updated"] += 1
        n["articles"] = sorted(added + n["articles"], key=lambda a: a["published"], reverse=True)[:KEEP_ARTICLES]
        n["article_count"] += len(added)
        n["reports"] = (new_reports + n["reports"])[:KEEP_REPORTS]
        n["status"] = "new" if n["first_seen"] == today else "updated"
        n["last_updated"] = today
        touched.add(n["id"])
        run_touched.add(n["id"])

    # (Status — new / updated / unchanged — is set from dates in finalize(), after all groups.)
    counts["ids"] = touched
    return counts


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
        if not comment and not drop:
            continue
        for r in drop:
            audit.append({"date": today, "group": n["group"], "story": n["title"], "text": strip_links(r["text"]),
                          "reason": "cited only an opinion or analysis piece (that is commentary, not reporting)"})
        n["articles"], n["reports"] = news, keep
        n["article_count"] = max(len(news), n["article_count"] - len(comment))
        removed += len(drop)
    return removed


def finalize(state: dict, today: str):
    """Counted, not judged: how many outlets reported each story today, and sourcing flags."""
    for n in state["narratives"]:
        # Status comes from DATES, not from this run, so running twice in a day gives the same
        # result as running once (the second run used to mark the morning's stories "unchanged").
        n["status"] = ("new" if n["first_seen"] == today
                       else "updated" if n["last_updated"] == today else "unchanged")
        todays = [a for a in n["articles"] if a.get("added") == today]
        outlets = {publisher(a["outlet"]) for a in todays}   # BBC World + BBC Africa = 1 outlet
        outlets |= {o for r in n["reports"] if r["date"] == today for o in r.get("outlets", [])}
        n["articles_today"] = len(todays)
        n["outlets_today"] = len(outlets)
        n["single_source_today"] = len(outlets) == 1
        n["state_media_only_today"] = bool(todays) and all(a.get("type") == "state-media" for a in todays)


def expire(state: dict, site_cfg: dict, today: str) -> list[str]:
    cutoff = (datetime.fromisoformat(today) - timedelta(days=site_cfg.get("expire_days", 6))).date().isoformat()
    gone = [n for n in state["narratives"] if n["last_updated"] < cutoff]
    for n in gone:
        state["narratives"].remove(n)
        state["archived"].insert(0, {k: n[k] for k in ("id", "group", "title", "first_seen", "last_updated", "article_count")})
    state["archived"] = state["archived"][:KEEP_ARCHIVED]
    return [n["title"] for n in gone]


# ── Putting it together ─────────────────────────────────────────────────────

def run_site(site: str, only_group: str | None, dry_run: bool):
    site_cfg, ai = load_site(site), load_ai()
    state = load_state(site)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    today = now.date().isoformat()
    first_run_since = (now - timedelta(hours=24)).isoformat()
    conn = store.connect()
    groups = [g for g in site_cfg["groups"] if not only_group or g["id"] == only_group]
    if not groups:
        raise SystemExit(f"No group '{only_group}' in config/{site}/site.yaml")
    names = {g["id"]: g["name"] for g in site_cfg["groups"]}

    print(f"\n=== {site_cfg['name']} ({ai.get('provider')}: {ai.get('model')}) ===")
    run_touched: set[str] = set()
    audit: list[dict] = []
    totals = Counter()
    for i, group in enumerate(groups):
        since = state["last_run"].get(group["id"], first_run_since)
        articles = select_articles(conn, site, group, since, ai)
        print(f"\n{group['name']}: {len(articles)} new articles")
        if not articles:
            if not dry_run:
                apply_result(state, group, {"narratives": []}, [], today, run_touched, audit)
            continue
        system, prompt = build_prompt(site_cfg, group, state["narratives"], articles, today)

        if dry_run:
            out = ROOT / "data" / "prompts" / f"{site}-{group['id']}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(f"=== SYSTEM ===\n{system}\n\n=== PROMPT ===\n{prompt}", encoding="utf-8")
            print(f"    dry run: prompt saved to {out.relative_to(ROOT)} (~{len(system + prompt) // 4:,} tokens)")
            continue

        if i > 0:
            time.sleep(ai.get("pause_seconds", 10))
        try:
            result = ask_json(system, prompt, SCHEMA)
        except LLMError as ex:
            print(f"    FAILED: {ex}")      # last_run isn't moved, so these articles are retried next run
            continue
        counts = apply_result(state, group, result, articles, today, run_touched, audit)
        totals.update({k: v for k, v in counts.items() if k != "ids"})
        state["last_run"][group["id"]] = now.isoformat()
        print(f"    -> {counts['new']} new, {counts['updated']} updated stories; "
              f"{counts['kept']} reports kept, {counts['rejected']} removed by guardrails"
              + (f" ({counts['repaired']} citations added by code)" if counts["repaired"] else "")
              + (f"; duplicates: {counts['merged']} stories merged, {counts['duplicate reports']} reports skipped"
                 if counts["merged"] or counts["duplicate reports"] else ""))
        for n in (n for n in state["narratives"] if n["id"] in counts["ids"]):
            elsewhere = f"  (in {names.get(n['group'], n['group'])})" if n["group"] != group["id"] else ""
            print(f"       [{n['status']:<7}] {n['title']}{elsewhere}")

    if not dry_run:
        for line in apply_corrections(state, site, today, audit):
            print(f"\nCorrection (config/{site}/corrections.yaml): {line}")
        dropped = drop_commentary(conn, state, site, today, audit)
        if dropped:
            print(f"\nRemoved {dropped} report(s) that rested only on opinion or analysis pieces")
        finalize(state, today)
        gone = expire(state, site_cfg, today)
        if gone:
            print(f"\nArchived (no reporting for {site_cfg.get('expire_days', 6)} days): " + "; ".join(gone))
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
    print(f"\n=== Removed by guardrails ({site}, last {AUDIT_DAYS} days): {len(entries)} ===")
    for e in entries[-40:]:
        print(f"\n  {e['date']} · {e['story']}\n    \"{e['text']}\"\n    -> {e['reason']}")


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
