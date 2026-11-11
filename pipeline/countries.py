"""
countries.py - which countries a story is about, and which region page it belongs on.

Usage:
  python pipeline/countries.py "Russia and Ukraine resume talks in Abu Dhabi"   # test a headline
  python pipeline/countries.py --stories                                        # place today's stories

No AI. The country list is config/geo/countries.yaml. For each story we COUNT country names in
its title, its reports and its headlines, then:
  - its countries   = the countries in its TITLE (what the reader sees), then any other country
                      with a fair share of the mentions; the most mentioned first
  - its region      = the region holding more than half of those countries' mentions; if no
                      region does (US-China trade, a G20 summit), the story goes on Global.
                      A title that starts with a country ("Poland: ...") settles it.
  - domestic or international = one country, or several
Placing stories by subject (not by the region of the outlets that reported them) means a story
about the US reported mostly by Asian outlets still appears under North America.
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from functools import lru_cache

from config import CONFIG, load_yaml

TITLE_WEIGHT = 2      # the story title counts double: it's the best single summary
KEEP_SHARE = 0.25     # a country needs a quarter of the top country's score to be listed
MIN_SCORE = 1.5       # ...and more than a passing mention
REGION_SHARE = 0.5    # a region needs MORE than half of the mentions to own the story; otherwise Global
MAX_COUNTRIES = 5


class Gazetteer:
    def __init__(self, cfg: dict, names: dict | None = None):
        self.countries = {c["id"]: c for c in cfg.get("countries", [])}
        self.terms: dict[str, str] = {}
        for c in self.countries.values():
            if not c.get("ambiguous"):
                self.terms[c["name"]] = c["id"]
            for word in c.get("also") or []:
                self.terms[str(word)] = c["id"]
        # Names in other languages (config/geo/country_names.yaml)
        for lang, table in (names or {}).items():
            for cid, words in (table or {}).items():
                if cid in self.countries:
                    for word in words or []:
                        self.terms.setdefault(str(word), cid)
        self.venues = {str(v).rstrip("*") for v in cfg.get("venues") or []}
        # Three kinds of name, three patterns (longest first, so "South Sudan" wins over "Sudan"):
        #   ordinary  whole words only                          Poland, États-Unis
        #   stems     "Испани*": the word may go on              Испания, Испании, Испанию
        #   CJK       no spaces between words in Chinese/Japanese, so match anywhere
        #   Arabic    may start with a one-letter prefix (و and, ب in, ل for, ف so, ك as)
        cjk = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
        arabic = re.compile(r"[\u0600-\u06ff]")
        self.stems = sorted((t[:-1], cid) for t, cid in self.terms.items() if t.endswith("*"))
        self.stems.sort(key=lambda x: -len(x[0]))
        words = [t for t in self.terms if not t.endswith("*") and not cjk.search(t) and not arabic.search(t)]
        alt = "|".join(re.escape(t) for t in sorted(words, key=len, reverse=True))
        stem_alt = "|".join(re.escape(s) + r"\w*" for s, _ in self.stems)
        self.pattern = re.compile(rf"(?<![\w-])({stem_alt + '|' if stem_alt else ''}{alt})(?![\w-])")
        self.cjk = [t for t in self.terms if cjk.search(t)]
        self.cjk_pattern = re.compile("|".join(re.escape(t) for t in sorted(self.cjk, key=len, reverse=True))) if self.cjk else None
        ar = [t for t in self.terms if arabic.search(t)]
        self.ar_pattern = re.compile(r"(?<![\w-])[وبلفك]?(" + "|".join(re.escape(t) for t in sorted(ar, key=len, reverse=True)) + r")(?![\w-])") if ar else None
        nots = sorted((str(n) for n in cfg.get("not_countries") or []), key=len, reverse=True)
        self.nots = re.compile(rf"(?<!\w)(?:{'|'.join(re.escape(n) for n in nots)})(?!\w)") if nots else None

    def lookup(self, text: str) -> str | None:
        """Which country a matched word means: an exact name, or the longest stem it starts with."""
        if text in self.terms:
            return self.terms[text]
        return next((cid for stem, cid in self.stems if text.startswith(stem)), None)

    def find(self, text: str) -> dict[str, float]:
        """{country id: weight} for one piece of text. A country counts once per text (1, or 0.25 as a venue)."""
        if self.nots:
            text = self.nots.sub(" ", text or "")
        found: dict[str, float] = {}
        hits = [m.group(1) for m in self.pattern.finditer(text or "")]
        if self.cjk_pattern:
            hits += [m.group(0) for m in self.cjk_pattern.finditer(text or "")]
        if self.ar_pattern:
            hits += [m.group(1) for m in self.ar_pattern.finditer(text or "")]
        for word in hits:
            cid = self.lookup(word)
            if cid:
                found[cid] = max(found.get(cid, 0), 0.25 if word in self.venues else 1.0)
        return found

    def tier(self, cid: str, kind: str) -> int:
        return int(self.countries[cid].get(kind) or 3)

    def region(self, cid: str) -> str:
        return self.countries[cid]["region"]

    def score(self, texts: list[str], title: str = "") -> Counter:
        sc = Counter()
        for cid, w in self.find(title).items():
            sc[cid] += w * TITLE_WEIGHT
        for t in texts:
            for cid, w in self.find(t).items():
                sc[cid] += w
        return sc

    def lead(self, title: str) -> str | None:
        """The country a title starts with, as in "Poland: ..." (a dateline). None if there isn't one."""
        m = self.pattern.match((title or "").strip())
        rest = (title or "").strip()[m.end():] if m else ""
        return self.terms[m.group(1)] if m and rest.lstrip().startswith(":") else None

    def place(self, scores: Counter, fallback: str, title: str = "") -> dict:
        """countries (title's first, then by mentions), region, and domestic / international."""
        named = [c for c, _ in sorted(self.find(title).items(), key=lambda kv: -scores.get(kv[0], kv[1]))]
        top = scores.most_common(1)[0][1] if scores else 0
        others = [c for c, s in scores.most_common() if c not in named and s >= max(MIN_SCORE, KEEP_SHARE * top)]
        keep = (named + others)[:MAX_COUNTRIES]
        if not keep:
            return {"countries": [], "region": fallback, "scope": None}
        lead = self.lead(title)
        if lead:
            region = self.region(lead)
        else:
            decide = named or keep                     # the title's countries decide, when it names any
            by_region = Counter()
            for c in decide:
                by_region[self.region(c)] += scores.get(c, 0) or 1
            best, share = by_region.most_common(1)[0]
            region = best if share > REGION_SHARE * sum(by_region.values()) else "global"
        return {"countries": keep, "region": region, "scope": "domestic" if len(keep) == 1 else "international"}


@lru_cache(maxsize=4)
def load(site: str = "geo") -> Gazetteer | None:
    path, names = CONFIG / site / "countries.yaml", CONFIG / site / "country_names.yaml"
    if not path.exists():
        return None
    return Gazetteer(load_yaml(path), load_yaml(names) if names.exists() else {})


def _demo(text: str):
    g = load("geo")
    sc = g.score([], text)
    print(f"\n  {text}\n  mentions: {dict(sc) or 'none'}\n  placed:   {g.place(sc, 'global', text)}")


def _stories():
    from datetime import date
    from narratives import load_state, strip_links
    g, state, today = load("geo"), load_state("geo"), date.today().isoformat()
    moved = 0
    for n in sorted(state["narratives"], key=lambda n: n["group"]):
        texts = [strip_links(r["text"]) for r in n["reports"][:10]] + [a["title"] for a in n["articles"]]
        p = g.place(g.score(texts, n["title"]), n["group"], n["title"])
        mark = "  " if p["region"] == n["group"] else "->"
        moved += mark == "->"
        print(f"{n['group']:>8} {mark} {p['region']:<8} {p['scope'] or '':<13} {', '.join(p['countries'])[:40]:<40} {n['title'][:60]}")
    print(f"\n{moved} of {len(state['narratives'])} stories move to the region they are about.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Find countries in text, or place today's stories.")
    ap.add_argument("text", nargs="*")
    ap.add_argument("--stories", action="store_true")
    a = ap.parse_args()
    if a.stories:
        _stories()
    else:
        for t in a.text or ["Russia and Ukraine resume talks in Abu Dhabi",
                            "US and China agree to pause tariffs", "Poland: Krakow shooting suspect charged",
                            "Georgia votes on new election law", "Tbilisi protesters rally against Georgian Dream"]:
            _demo(t)
