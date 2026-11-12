"""
cluster.py - group headlines about the same event BEFORE the AI sees them. No AI.

Usage:
  python pipeline/cluster.py --site geo          # cluster the last 24 hours and print the biggest groups
  python pipeline/cluster.py --site geo --hours 48 --show 60

Why: asking the AI to find the stories in 1,000 headlines at once means it finds 10 or 20 and
misses the rest. Measured on one day of English headlines: 142 events reported by 2+ outlets,
68 by 3+, 25 by 5+, while the AI tracked about 30. So code does the grouping (cheap, complete,
repeatable) and the AI only checks each small group and writes the reports.

How two headlines are compared:
  - their rare words count, common words don't. "Abu Dhabi", "trilateral", "Hegseth" are rare
    in a day's news; "says", "new", "government" are everywhere. Rarity is measured on the
    batch itself (inverse document frequency, IDF).
  - two headlines are about the same event when they share at least 3 rare words worth at
    least 14 points together (the summary's words count half), and at least one of those words
    is a NAME (capitalised inside a headline). Without that, "Gunmen attack leaves one dead" and
    "Airstrike on hospital leaves six dead" would match on their common words alone.
  - if both name countries and none in common, they are never the same event.
Each new headline joins the most similar group, or starts its own.
"""
from __future__ import annotations

import argparse
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import countries as gazetteer
import guardrails

RARE = 2.0          # a word must be at least this rare (IDF) to count
MIN_SHARED = 3      # rare title words two headlines must share...
MIN_SCORE = 14.0    # ...worth at least this much together, one of them a name
STRONG = 24.0       # ...or this much, names or not (headlines in Title Case, scripts without capitals)
SUMMARY_WEIGHT = 0.5


# Little words of the other languages in the feeds (accents removed). Without them, "los" or "der"
# look "rare" on a day when most headlines are in English, and unrelated Spanish headlines match.
STOP_OTHER = set("""
los las del por para con una uno unos unas que mas sus sin sobre entre tras como desde hasta este esta estos
hoy ano anos dia dias vivo directo asi fue ser son esta estan tiene dice segun ante pero muy ya
dos das nos nas pelo pela com uma sem sobre apos como entre mais seu sua seus suas hoje ano anos dia diz ser
des les une sur par pour avec dans aux ses est sont pas plus apres selon entre comme cette ces leur
der die das den dem des und mit von fur auf aus bei nach nicht ist sind ein eine einen einem einer vor uber wie
gli della delle dei degli nel nella con per una che sono dopo tra
van het een met voor niet zijn naar ook
och att det som med for till har inte
""".split())


def tokens(text: str) -> set[str]:
    """Words of any language, lower case, accents removed, roughly stemmed. Short and common words dropped."""
    out = set()
    for w in re.findall(r"\w[\w'’\-]+", guardrails.plain(text or "")):
        w = re.sub(r"['’]s$", "", w).strip("-'’")
        if len(w) > 2 and w not in guardrails.STOPWORDS and w not in STOP_OTHER and not w.isdigit():
            out.add(guardrails.stem(w))
    return out


def names(text: str) -> set[str]:
    """
    Tokens of the words written with a capital inside a headline: places, people, organisations.
    The first word counts only if it is a known name (countries.yaml, entities.yaml), since every
    headline starts with a capital. In scripts without capitals (Arabic, Chinese...) every word counts.
    """
    out, first = set(), True
    g = gazetteer.load("geo")
    for m in re.finditer(r"\w[\w'’\-]+", text or ""):
        w = m.group(0)
        if not first and (w[0].isupper() or not w[0].isalpha() or w[0].lower() == w[0].upper()):
            out |= tokens(w)
        elif first and g and g.lookup(w):    # a first word that is a known place, person or company
            out |= tokens(w)
        first = False if w[0].isalpha() or w[0].isdigit() else first
        if text[max(0, m.start() - 2):m.start()].strip() in (":", "|", "-", "–"):
            out |= tokens(w)                 # "Spain: General strike": after a colon, still a name
    return out


class Index:
    """Rarity (IDF) of every word in a batch of articles."""

    def __init__(self, docs: list[set[str]]):
        n = max(len(docs), 1)
        df = Counter(w for d in docs for w in d)
        self.idf = {w: math.log(n / (1 + k)) for w, k in df.items()}
        self.unknown = math.log(n)          # a word never seen in the batch is as rare as it gets

    def rare(self, words: set[str]) -> set[str]:
        return {w for w in words if self.idf.get(w, self.unknown) > RARE}

    def score(self, a_title: set[str], b: set[str], a_summary: set[str] = frozenset()) -> tuple[float, int]:
        """(points, shared title words) between one article's words and a group's words."""
        shared = a_title & b
        pts = sum(self.idf.get(w, self.unknown) for w in shared)
        pts += SUMMARY_WEIGHT * sum(self.idf.get(w, self.unknown) for w in (a_summary - a_title) & b)
        return pts, len(shared)

    def passes(self, a: set[str], a_names: set[str], b: set[str], b_names: set[str],
               a_summary: set[str] = frozenset()) -> float:
        """The grouping test. Returns the points if it passes, else 0."""
        pts, shared = self.score(a, b, a_summary)
        if shared < MIN_SHARED or pts < MIN_SCORE:
            return 0.0
        if pts >= STRONG or (a & b) & (a_names | b_names):
            return pts
        return 0.0


def _countries(g, text: str) -> set[str]:
    return {c for c, w in g.find(text).items() if w >= 0.5} if g else set()


def index_for(articles: list[dict]) -> Index:
    """Word rarity measured on these articles (headline and start of summary)."""
    return Index([tokens(a["title"]) | tokens((a.get("summary") or "")[:300]) for a in articles])


def cluster(articles: list[dict], site: str = "geo", idx: Index | None = None) -> list[list[dict]]:
    """
    Groups of articles, biggest first. Every article ends up in exactly one group (often alone).
    Articles are dicts with at least 'title'; 'summary' and 'published' are used when present.
    """
    g = gazetteer.load(site)
    arts = sorted(articles, key=lambda a: a.get("published") or "")
    titles = [tokens(a["title"]) for a in arts]
    summaries = [tokens((a.get("summary") or "")[:300]) for a in arts]
    idx = idx or Index([t | s for t, s in zip(titles, summaries)])
    groups: list[dict] = []
    by_word: dict[str, set[int]] = {}         # word -> groups that match on it (so we only compare those)
    for a, t, s in zip(arts, titles, summaries):
        t, s = idx.rare(t), idx.rare(s)
        nm = names(a["title"]) & t
        where = _countries(g, a["title"])
        best, best_pts = None, 0.0
        near = Counter(i for w in t for i in by_word.get(w, ()))
        for i, k in near.items():
            if k < MIN_SHARED:
                continue
            grp = groups[i]
            if where and grp["countries"] and not where & grp["countries"]:
                continue
            pts = idx.passes(t, nm, grp["match"], grp["names"], s)
            if pts > best_pts:
                best, best_pts = grp, pts
        if best is None:
            groups.append({"items": [a], "lead": t, "seen": Counter(t), "match": set(t), "countries": set(where),
                           "lead_countries": set(where), "where": Counter(where), "names": set(nm)})
            for w in t:
                by_word.setdefault(w, set()).add(len(groups) - 1)
            continue
        best["items"].append(a)
        best["seen"].update(t)
        best["where"].update(where)
        best["names"] |= nm
        # A group is matched on its first headline's words plus words that several of its headlines
        # share (2, or 15% of a big group): it can't drift away from its event one loose match at a
        # time. Same for countries: the group's countries are those in its first headline or in a
        # quarter of its headlines.
        n = len(best["items"])
        best["match"] = best["lead"] | {w for w, k in best["seen"].items() if k >= max(2, math.ceil(0.15 * n))}
        best["countries"] = best["lead_countries"] | {c for c, k in best["where"].items() if k >= max(2, n / 4)}
        i = groups.index(best)
        for w in best["match"]:
            by_word.setdefault(w, set()).add(i)
    out = [grp["items"] for grp in groups]
    out.sort(key=lambda items: (-len({publisher_of(a) for a in items}), -len(items)))
    return out


def features(idx: Index, title: str) -> tuple[set[str], set[str]]:
    """(rare words, rare names) of one headline."""
    t = idx.rare(tokens(title))
    return t, names(title) & t


def close(idx: Index, a: dict, b: dict) -> bool:
    """Do two articles pass the grouping test directly (not via a group)? Used before code adds an article to a story."""
    return idx.passes(*features(idx, a["title"]), *features(idx, b["title"])) > 0


def same_story_share(idx: Index, a_titles: list[str], b_titles: list[str]) -> float:
    """
    Share of one story's headlines that pass the grouping test against a headline of the other
    (the higher of the two directions). Measured on real stories: true duplicates 0.6-1.0,
    different stories up to 0.5 (and those differed in country, which is checked separately).
    """
    A = [features(idx, t) for t in a_titles if t]
    B = [features(idx, t) for t in b_titles if t]

    def share(X, Y):
        hits = sum(1 for x in X if any(idx.passes(*x, *y) for y in Y))
        return hits / len(X) if X else 0.0
    return max(share(A, B), share(B, A))


def publisher_of(a: dict) -> str:
    return a.get("publisher") or a.get("outlet") or a.get("source") or ""


class Stories:
    """
    Tracked stories, ready to be matched against today's groups. A group continues a story when
    at least a third of its headlines (and at least one) pass the grouping test against the
    story's title or one of its recent headlines, and their countries don't clash.
    """

    def __init__(self, stories: list[dict], idx: Index, site: str = "geo"):
        self.idx, self.g = idx, gazetteer.load(site)
        self.items = []
        for n in stories:
            titles = [n["title"]] + [a["title"] for a in n.get("articles", [])[:12]]
            where = set().union(*(_countries(self.g, t) for t in titles))
            self.items.append((n, [features(idx, t) for t in titles], where))
        self.by_word: dict[str, set[int]] = {}
        for i, (_, heads, _) in enumerate(self.items):
            for h, _ in heads:
                for w in h:
                    self.by_word.setdefault(w, set()).add(i)

    def match(self, items: list[dict]) -> tuple[dict | None, int]:
        """(story, number of the group's headlines that matched it), or (None, 0)."""
        heads = [features(self.idx, a["title"]) for a in items[:8]]
        where = set().union(*(_countries(self.g, a["title"]) for a in items[:8])) if items else set()
        near = {i for h, _ in heads for w in h for i in self.by_word.get(w, ())}
        best, best_hits = None, 0
        for i in near:
            n, theirs, countries = self.items[i]
            if where and countries and not where & countries:
                continue
            hits = sum(1 for h in heads if any(self.idx.passes(*h, *t) for t in theirs))
            if hits and hits * 3 >= len(heads) and hits > best_hits:
                best, best_hits = n, hits
        return best, best_hits


def _demo(site: str, hours: int, show: int):
    import store
    from narratives import publisher
    conn = store.connect()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM articles WHERE site=? AND published >= ? AND COALESCE(kind, 'news')='news'", (site, since))]
    for r in rows:
        r["publisher"] = publisher(r["outlet"])
    groups = cluster(rows, site)
    pubs = [len({publisher_of(a) for a in grp}) for grp in groups]
    print(f"{len(rows)} news articles in {hours}h -> {len(groups)} groups: "
          f"{sum(p >= 2 for p in pubs)} reported by 2+ outlets, {sum(p >= 3 for p in pubs)} by 3+, {sum(p >= 5 for p in pubs)} by 5+")
    for grp, p in list(zip(groups, pubs))[:show]:
        regions = len({a.get("region") for a in grp})
        print(f"  {p:>3} outlets, {len(grp):>3} articles, {regions} regions | {grp[0]['title'][:95]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Group headlines about the same event (no AI).")
    ap.add_argument("--site", default="geo")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--show", type=int, default=40)
    a = ap.parse_args()
    _demo(a.site, a.hours, a.show)
