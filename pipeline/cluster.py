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
  - a word that is common IN ITS OWN LANGUAGE never counts, however rare it looks across all
    languages: the little words of each language are listed below, and in a language with
    enough headlines, a word in more than 12% of them is treated as common too. Otherwise two
    unrelated Bulgarian headlines would "match" on the Bulgarian for "after" and "over".
  - two headlines are about the same event when they share at least 3 rare words worth at
    least 16 points together (or 20 points without a shared name) (the summary's words count half), and at least one of those words
    is a NAME (capitalised inside a headline). Without that, "Gunmen attack leaves one dead" and
    "Airstrike on hospital leaves six dead" would match on their common words alone.
  - if both name countries and none in common, they are never the same event.
Each new headline joins the most similar group, or starts its own.
"""
from __future__ import annotations

import argparse
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import countries as gazetteer
import guardrails

# Tuned on a labelled day (pipeline/evaluate_grouping.py, tests/data/grouping_day.json.gz):
# precision 0.968, recall 0.563 (the earlier 14/24 scored 0.957 and 0.561). Lower scores grouped
# more but mixed in unrelated look-alikes (separate drone strikes, two budgets); RARE between 1.5
# and 2.5 and MIN_SHARED 2 or 3 made no difference.
RARE = 2.0          # a word must be at least this rare (IDF) to count
MIN_SHARED = 3      # rare title words two headlines must share...
MIN_SCORE = 16.0    # ...worth at least this much together, one of them a name
STRONG = 20.0       # ...or this much, names or not (headlines in Title Case, scripts without capitals)
SUMMARY_WEIGHT = 0.5
LANG_COMMON = 0.12  # in a language with LANG_MIN_DOCS+ headlines, a word in this share of them is common
LANG_MIN_DOCS = 150
MERGE_SCORE = 18.0  # merging two tracked stories (merge_duplicates) needs this much: nothing checks it after
# Looser test for "does this article belong to that tracked story?" (follow-ups use new words)
RELATED_SHARED, RELATED_SCORE = 2, 9.0
# Telling code "this group continues story X" needs a DISTINCTIVE shared name: not a country or
# capital (countries.yaml), and not a name in more than 2% of the run's headlines (Trump, Gaza).
# "Guerre en Ukraine: ... Poutine" and "Guerre en Ukraine: ... Starshield" share only those.
DISTINCT_SHARE = 0.02

# Little words of the other languages in the feeds. Without them, "los" or "след" look "rare" on a
# day when most headlines are in English, and unrelated headlines in that language match.
# Words of one or two letters are ignored anyway. Written normally; accents are removed on loading.
_STOP_OTHER = """
los las del por para con una uno unos unas que mas sus sin sobre entre tras como desde hasta este esta estos
hoy año años día días vivo directo así fue ser son están tiene dice según ante pero muy contra durante cuando
donde porque aunque también solo todo todos toda todas otro otra otros nuevo nueva nuevos puede pueden hace
hacer tienen hay era será han esto eso ese esa aquí minuto última hora fotos foto video videos
dos das nos nas pelo pela com uma sem após até mais seu sua seus suas hoje diz dizem não são tem veja quando
onde também pode podem foi isso isto muito novo nova vai vão
des les une sur par pour avec dans aux ses est sont pas plus après avant selon comme cette ces leur leurs ont
fait faire tout tous toute nouveau nouvelle deux trois depuis sans sous chez aussi encore direct
der die das den dem des und mit von für auf aus bei nach nicht ist sind ein eine einen einem einer vor über wie
bis diese dieser dieses jetzt sie wir ihr auch noch nur schon wird werden wurde wurden hat haben hatte kann soll
muss gegen unter zwischen durch ohne neue neuer neues mehr alle beim zum zur vom ins seit wegen dass oder aber
als wenn was wer
gli della dello delle dei degli nel nella nei sul sulla che sono dopo tra fra anche più ancora senza sotto
sopra ecco
van het een met voor niet zijn naar ook dit bij dat moet maar uit als onder aan kan jij door nog wel meer geen
over tegen worden wordt werd heeft hebben deze nieuwe live
och att det som med för till har inte mot efter ett den var när från ska vill mer alla nya nytt blir blev hade
kommer
się nie jest dla jak przed chce oraz ale czy tak już jego jej ich przez pod nad bez który która które był była
było będą będzie może trzeba tylko nowy nowa nowe teraz kiedy gdzie jako albo lub tym tego temu
заявил заявила заявили рассказал рассказала сообщил сообщила сообщили который которые которая которого после
также может могут будет были было была этот этом этого эти чтобы когда где почему как так только уже еще ещё
все всех его ее её их них для при над под без про через против около между года году лет новый новые новая
стало стал стала назвал назвала время
та що які який яка після також буде цей ця ці щоб коли чому лише вже всі її їх під проти заявив повідомив розповів
след към срещу още вече само като това тази този тези които който която което най ще има няма беше били бил
била заради защото според каза заяви нов нова нови година години днес
ovo evo samo sta šta koji koja koje sam kako nije još već biti bio bila bilo bili zbog nakon prije posle poslije
tokom između ispred iza kod više novi novo danas sutra jučer juče ali ili kao što sve svi ima nema može treba
rekao rekla kazao kazala izjavio izjavila
ово ево само шта који која које сам како није још већ бити био била било били због након пре после током између
код више нови нова ново данас али или као што све сви има нема може треба рекао рекла изјавио
ile için gibi kadar sonra önce daha olan oldu olarak olacak yeni bir iki üç ve veya ama ancak çok her hem ise
dedi açıklama açıkladı son dakika bugün
على الى إلى بعد قبل في من عن مع هذا هذه التي الذي الذين كان كانت يكون حول خلال بين ضد منذ حتى لدى عند أن إن
لا ما لم لن قد كل بعض غير أكثر اليوم عاجل فيديو بالفيديو بالصور
мен және үшін бойынша туралы жаңа кейін дейін бұл осы сол деп болды болады
dhe për nga një që pas para mbi nën janë është ishte kanë këtë kjo këto ata ato por edhe vetëm tani sot
kun jos mutta myös nyt vain viela vielä kanssa jälkeen ennen mukaan uusi uuden ovat oli olivat
video videos photos watch breaking update updates exclusive latest
how why says said say tells told could would will may might must get gets got make makes made
"""
STOP_OTHER = {guardrails.plain(w) for w in _STOP_OTHER.split()}


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
    """Rarity (IDF) of every word in a batch of articles, and the words common in each language."""

    def __init__(self, docs: list[set[str]], langs: list[str | None] | None = None):
        n = max(len(docs), 1)
        df = Counter(w for d in docs for w in d)
        self.idf = {w: math.log(n / (1 + k)) for w, k in df.items()}
        self.unknown = math.log(n)          # a word never seen in the batch is as rare as it gets
        # a distinctive name is in at most 2% of the headlines (or 2 headlines in a small run)
        self.distinct_idf = math.log(n / (1 + max(2, DISTINCT_SHARE * n)))
        self.common: dict[str, set[str]] = {}
        by_lang: dict[str, list[set[str]]] = defaultdict(list)
        for d, lang in zip(docs, langs or []):
            by_lang[lang or "en"].append(d)
        for lang, ds in by_lang.items():
            if len(ds) >= LANG_MIN_DOCS:
                dfl = Counter(w for d in ds for w in d)
                self.common[lang] = {w for w, k in dfl.items() if k >= LANG_COMMON * len(ds)}

    def rare(self, words: set[str], lang: str | None = None) -> set[str]:
        common = self.common.get(lang or "en", set())
        return {w for w in words if self.idf.get(w, self.unknown) > RARE and w not in common}

    def score(self, a_title: set[str], b: set[str], a_summary: set[str] = frozenset()) -> tuple[float, int]:
        """(points, shared title words) between one article's words and a group's words."""
        shared = a_title & b
        pts = sum(self.idf.get(w, self.unknown) for w in shared)
        pts += SUMMARY_WEIGHT * sum(self.idf.get(w, self.unknown) for w in (a_summary - a_title) & b)
        return pts, len(shared)

    def passes(self, a: set[str], a_names: set[str], b: set[str], b_names: set[str],
               a_summary: set[str] = frozenset(), min_shared: int | None = None, min_score: float | None = None,
               distinct: bool = False) -> float:
        """
        The grouping test. Returns the points if it passes, else 0.
        distinct=True: the shared name must be distinctive (see DISTINCT_SHARE), for story continuations.
        """
        min_shared = MIN_SHARED if min_shared is None else min_shared     # read now, so the evaluation can tune them
        min_score = MIN_SCORE if min_score is None else min_score
        pts, shared = self.score(a, b, a_summary)
        if shared < min_shared or pts < min_score:
            return 0.0
        common_names = (a & b) & (a_names | b_names)
        if distinct:
            common_names = {w for w in common_names
                            if w not in place_tokens() and self.idf.get(w, self.unknown) >= self.distinct_idf}
        if pts >= STRONG or common_names:
            return pts
        return 0.0


_PLACES: set[str] | None = None


def place_tokens() -> set[str]:
    """Word tokens of every country, demonym and capital in countries.yaml and country_names.yaml."""
    global _PLACES
    if _PLACES is None:
        g = gazetteer.load("geo")
        _PLACES = {w for t in (g.country_terms if g else ()) for w in tokens(t.rstrip("*"))}
    return _PLACES


def _countries(g, text: str) -> set[str]:
    return {c for c, w in g.find(text).items() if w >= 0.5} if g else set()


def index_for(articles: list[dict]) -> Index:
    """Word rarity measured on these articles (headline and start of summary)."""
    return Index([tokens(a["title"]) | tokens((a.get("summary") or "")[:300]) for a in articles],
                 [a.get("lang") for a in articles])


def features(idx: Index, title: str, lang: str | None = None) -> tuple[set[str], set[str]]:
    """(rare words, rare names) of one headline."""
    t = idx.rare(tokens(title), lang)
    return t, names(title) & t


def cluster(articles: list[dict], site: str = "geo", idx: Index | None = None) -> list[list[dict]]:
    """
    Groups of articles, biggest first. Every article ends up in exactly one group (often alone).
    Articles are dicts with at least 'title'; 'summary', 'published' and 'lang' are used when present.
    """
    g = gazetteer.load(site)
    arts = sorted(articles, key=lambda a: a.get("published") or "")
    idx = idx or index_for(arts)
    groups: list[dict] = []
    by_word: dict[str, set[int]] = {}         # word -> groups that match on it (so we only compare those)
    for a in arts:
        t, nm = features(idx, a["title"], a.get("lang"))
        s = idx.rare(tokens((a.get("summary") or "")[:300]), a.get("lang"))
        where = _countries(g, a["title"])
        best, best_pts = None, 0.0
        near = Counter(i for w in t for i in by_word.get(w, ()))
        for i, k in sorted(near.items()):          # in a fixed order, so a tie always goes the same way
            if k < MIN_SHARED:
                continue
            grp = groups[i]
            if where and grp["countries"] and not where & grp["countries"]:
                continue
            pts = idx.passes(t, nm, grp["match"], grp["names"], s)
            if pts > best_pts:
                best, best_pts = grp, pts
        if best is None:
            groups.append({"i": len(groups), "items": [a], "lead": t, "seen": Counter(t), "match": set(t),
                           "countries": set(where), "lead_countries": set(where), "where": Counter(where),
                           "names": set(nm)})
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
        for w in best["match"]:
            by_word.setdefault(w, set()).add(best["i"])
    out = [grp["items"] for grp in groups]
    out.sort(key=lambda items: (-len({publisher_of(a) for a in items}), -len(items)))
    return out


def close(idx: Index, a: dict, b: dict) -> bool:
    """Do two articles pass the grouping test directly (not via a group)? Used before code adds an article to a story."""
    return idx.passes(*features(idx, a["title"], a.get("lang")), *features(idx, b["title"], b.get("lang"))) > 0


def story_heads(story: dict, n: int = 12) -> list[tuple[str, str | None]]:
    """(headline, language) for a tracked story: its title and wider-story name (English), and its newest headlines."""
    heads = [(story["title"], "en")]
    if story.get("label") and story["label"] != story["title"]:
        heads.append((story["label"], "en"))
    return heads + [(a["title"], a.get("lang")) for a in story.get("articles", [])[:n]]


# Headlines that make poor titles: live blogs, explainers, questions, video pages.
NOT_A_TITLE = re.compile(r"\b(live|live updates|as it happened|what we know|what to know|explained|explainer|"
                         r"podcast|newsletter|watch|video|photos|in pictures|opinion|analysis)\b|\?\s*$", re.I)
LEAD_MIN_ARTICLES = 3   # a day needs this many articles in a story before a headline can become its title
LEAD_SUPPORT = 0.4      # ...and the headline must match this share of the day's other outlets (at least 2)


def lead_headline(idx: Index, articles: list[dict], site: str = "geo") -> tuple[dict | None, int, int]:
    """
    The real headline that best represents these articles (one day of a story's coverage): the
    English headline that matches the most OTHER outlets' headlines (pair_related), wires and
    international outlets first on a tie, then the one closest to a normal headline length. A state
    outlet's headline is used only when no other outlet's headline qualifies.
    Returns (article or None, outlets backing it, outlets that could). None when the day has fewer
    than LEAD_MIN_ARTICLES articles, or no headline is backed by LEAD_SUPPORT of the other outlets:
    a one-off headline (an unrelated article filed under the story) can never become its title.
    """
    if len(articles) < LEAD_MIN_ARTICLES:
        return None, 0, 0
    g = gazetteer.load(site)
    pubs = {publisher_of(a) for a in articles}

    def usable(a):
        return (a.get("lang") or "en") == "en" and not NOT_A_TITLE.search(a["title"]) and 20 <= len(a["title"]) <= 150
    candidates = [a for a in articles if usable(a) and a.get("type") != "state-media"] \
        or [a for a in articles if usable(a)]
    best, best_key, best_backing = None, None, 0
    for a in candidates:
        backing = {publisher_of(b) for b in articles if b is not a and publisher_of(b) != publisher_of(a)
                   and pair_related(idx, a, b, g)}
        key = (len(backing), a.get("type") in ("wire", "international"), -abs(len(a["title"]) - 80), a["title"])
        if best_key is None or key > best_key:
            best, best_key, best_backing = a, key, len(backing)
    others = len(pubs) - 1
    need = max(2, math.ceil(others * LEAD_SUPPORT))
    return (best if best is not None and best_backing >= need else None), best_backing, others


def story_support(idx: Index, text: str, articles: list[dict], site: str = "geo") -> float | None:
    """
    Share of a story's English headlines that `text` fits: they share a rare word that isn't a
    place ("Fairford", "talks", "outage"), and their countries don't clash. A shared country alone
    doesn't count: every name for a Polish story "fits" a Polish headline. Used to check a proposed
    wider-story name: it must fit most of the story, not one day of it. None with fewer than 3.
    """
    english = [a for a in articles if (a.get("lang") or "en") == "en"]
    if len(english) < 3:
        return None
    g = gazetteer.load(site)
    words = idx.rare(tokens(text), "en") - place_tokens()
    where = _countries(g, text)

    def fits(a):
        theirs = _countries(g, a["title"])
        return not (where and theirs and not where & theirs) and bool(words & idx.rare(tokens(a["title"]), "en"))
    return sum(1 for a in english if fits(a)) / len(english)


def same_story_share(idx: Index, a_heads: list[tuple[str, str | None]], b_heads: list[tuple[str, str | None]]) -> float:
    """
    Share of one story's headlines that pass the grouping test against a headline of the other
    (the higher of the two directions). Measured on real stories: true duplicates 0.6-1.0,
    different stories up to 0.5 (and those differed in country, which is checked separately).
    """
    A = [features(idx, t, lang) for t, lang in a_heads if t]
    B = [features(idx, t, lang) for t, lang in b_heads if t]

    # Stricter than grouping (no AI checks a merge): more points and a distinctive name.
    def share(X, Y):
        hits = sum(1 for x in X if any(idx.passes(*x, *y, min_score=MERGE_SCORE, distinct=True) for y in Y))
        return hits / len(X) if X else 0.0
    return max(share(A, B), share(B, A))


def related(idx: Index, articles: list[dict], story: dict, site: str = "geo") -> bool:
    """
    Does at least one of these articles plausibly belong to this tracked story? A looser test than
    grouping (two rare words in common, one of them a name), because follow-ups use new words;
    and never across countries. Used to check the AI's "this continues story X" when code didn't
    suggest it: it catches unrelated news from the same country glued onto an old story.
    """
    g = gazetteer.load(site)
    heads = story_heads(story)
    theirs = [features(idx, t, lang) for t, lang in heads]
    where = set().union(*(_countries(g, t) for t, _ in heads)) if g else set()
    for a in articles:
        mine = _countries(g, a["title"]) if g else set()
        if mine and where and not mine & where:
            continue
        f = features(idx, a["title"], a.get("lang"))
        if any(idx.passes(*f, *t, min_shared=RELATED_SHARED, min_score=RELATED_SCORE, distinct=True) for t in theirs):
            return True
    return False


def pair_related(idx: Index, a: dict, b: dict, g=None) -> bool:
    """Two articles plausibly about the same story: the loose test, a distinctive shared name, no country clash."""
    if g:
        ca, cb = _countries(g, a["title"]), _countries(g, b["title"])
        if ca and cb and not ca & cb:
            return False
    return idx.passes(*features(idx, a["title"], a.get("lang")), *features(idx, b["title"], b.get("lang")),
                      min_shared=RELATED_SHARED, min_score=RELATED_SCORE, distinct=True) > 0


def loose_link(idx: Index, a: dict, b: dict, g=None) -> bool:
    """
    The loosest sign two articles belong to one story, used to find articles that have NOTHING to do
    with the story they were filed under: a country in common (in any language, so translations
    count), or two rare words in common, or one rare name. Never when their countries differ.
    """
    ca = _countries(g, a["title"]) if g else set()
    cb = _countries(g, b["title"]) if g else set()
    if ca and cb:
        return bool(ca & cb)
    ta, na = features(idx, a["title"], a.get("lang"))
    tb, nb = features(idx, b["title"], b.get("lang"))
    common = ta & tb
    return len(common) >= 2 or bool(common & (na | nb))


def connected(idx: Index, core: list[dict], others: list[dict], site: str = "geo") -> tuple[list[dict], list[dict]]:
    """
    Which of `others` are connected to the core of a story, directly or through each other
    (loose_link): a story can move on (talks -> prisoner swap -> envoys' visit) as long as each
    step shares something with an earlier one. Returns (connected, not connected).
    """
    g = gazetteer.load(site)
    kept, rest = list(core), list(others)
    changed = True
    while changed and rest:
        changed = False
        for a in list(rest):
            if any(loose_link(idx, a, k, g) for k in kept):
                kept.append(a)
                rest.remove(a)
                changed = True
    return kept[len(core):], rest


def title_support(idx: Index, title: str, articles: list[dict]) -> float | None:
    """
    Share of these (English) headlines that still match the story's title. None if there are too
    few English headlines to judge (titles are written in English).
    """
    english = [a for a in articles if (a.get("lang") or "en") == "en"]
    if len(english) < 3:
        return None
    # A headline supports the title when they share a rare word that isn't just a place: "GitHub",
    # "Colom", "floods". "Gaza" alone doesn't make an airstrike story fit a floods title.
    t = idx.rare(tokens(title), "en") - place_tokens()
    hits = sum(1 for a in english if t & idx.rare(tokens(a["title"]), "en"))
    return hits / len(english)


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
            heads = story_heads(n)
            where = set().union(*(_countries(self.g, t) for t, _ in heads))
            self.items.append((n, [features(idx, t, lang) for t, lang in heads], where))
        self.by_word: dict[str, set[int]] = {}
        for i, (_, heads, _) in enumerate(self.items):
            for h, _ in heads:
                for w in h:
                    self.by_word.setdefault(w, set()).add(i)

    def match(self, items: list[dict]) -> tuple[dict | None, int]:
        """(story, number of the group's headlines that matched it), or (None, 0)."""
        heads = [features(self.idx, a["title"], a.get("lang")) for a in items[:8]]
        where = set().union(*(_countries(self.g, a["title"]) for a in items[:8])) if items else set()
        near = {i for h, _ in heads for w in h for i in self.by_word.get(w, ())}
        best, best_hits = None, 0
        for i in sorted(near):
            n, theirs, countries = self.items[i]
            if where and countries and not where & countries:
                continue
            hits = sum(1 for h in heads if any(self.idx.passes(*h, *t, distinct=True) for t in theirs))
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
