"""
guardrails.py - checks every AI-written sentence against the articles it cites.

The AI is allowed to do one thing with words: restate what an outlet reported. These
checks make sure it did only that. They're plain, predictable code, not another AI,
so the same sentence always gets the same verdict and you can read exactly why.

  check(sentence, cited_articles)  ->  (True, "")  or  (False, "reason it was rejected")

Run the built-in examples to see each check catch something:
  python pipeline/guardrails.py
"""
from __future__ import annotations

import re
import unicodedata

from config import CONFIG, load_yaml

CITE = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")

# Capitalised words that aren't names, so they shouldn't count in the name check.
NOT_NAMES = set("""
The This That These Those There Their They It Its He She His Her We Our A An And But Or Of In On At To For From By With
After Before During While When Where Who What Which As According Also However Meanwhile Separately Earlier Later
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September
October November December President Prime Minister Minister Ministry Government Police Army Military Officials Official
Authorities Court Parliament State Federal National Secretary General Chief Head Spokesperson Spokesman Spokeswoman
Mr Mrs Ms Dr North South East West New
""".split())

_cfg = None


def cfg() -> dict:
    global _cfg
    if _cfg is None:
        _cfg = load_yaml(CONFIG / "guardrails.yaml")
    return _cfg


def plain(text: str) -> str:
    """Lowercase, accents removed ('Kraków' -> 'krakow'), so spelling variants still match."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
NUMBER_WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
                     "eighty": "80", "ninety": "90", "dozen": "12"})
NUMBER_WORDS.pop("one")  # "one of the..." is too common to treat as a count


def numbers_in(text: str) -> set[str]:
    """'$6.3bn', '1,200 people', '80%', 'four tankers' -> {'6.3', '1200', '80', '4'}"""
    out = set()
    for m in re.findall(r"(?<![\w.])\d+(?:[.,]\d+)*", text or ""):
        n = m.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", m) else m.replace(",", ".")
        out.add(n.rstrip(".").lstrip("0") or "0")
    for w in re.findall(r"[a-z]+", plain(text)):     # numbers written as words count too
        if w in NUMBER_WORDS:
            out.add(NUMBER_WORDS[w])
    return out


def names_in(sentence: str) -> set[str]:
    """Capitalised words that look like names (not the first word, not common words)."""
    words = [re.sub(r"['’]s$", "", w) for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]+", sentence)]  # ANC's -> ANC
    return {w for i, w in enumerate(words) if i > 0 and w[0].isupper() and w not in NOT_NAMES and len(w) > 2}


STOPWORDS = set("""
a an the and or but of in on at to for from by with as is are was were be been being has have had
that this these those it its their they them he she his her we our you your who whom which what when
where while than then there here also not no into over after before about against between during
under up down out off more most other some such only own same so very can will would should just
""".split())


def stem(w: str) -> str:
    """Rough word root, so 'tankers'/'tanker' and 'counted'/'counting' match. Good enough for checking."""
    for suffix in ("ing", "ed", "es", "s", "ly"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


def content_words(text: str, skip: set[str]) -> list[str]:
    words = [re.sub(r"['’]s$", "", w) for w in re.findall(r"[a-z][a-z'’\-]+", plain(text))]
    return [w for w in words if w not in STOPWORDS and w not in skip and len(w) > 2]


def source_text(articles: list[dict]) -> str:
    """Everything the cited articles say (headline + summary) that a sentence may draw on."""
    return " ".join(f"{a.get('title', '')} {a.get('summary', '')}" for a in articles)


def check(sentence: str, cited: list[dict]) -> tuple[bool, str]:
    c = cfg()
    if not CITE.search(sentence or "") or not cited:
        return False, "no citation"                                            # check 1
    body = CITE.sub(" ", sentence)
    body_plain, src_plain = plain(body), plain(source_text(cited))

    if len(body.split()) > c.get("max_words", 45):
        return False, f"too long ({len(body.split())} words)"

    verbs = c.get("reporting_verbs", [])
    if not any(re.search(rf"\b{re.escape(v)}\b", body_plain) for v in verbs):
        return False, "not attributed (no reporting verb)"                     # check 2

    if c.get("check_numbers", True):                                           # check 3
        missing = numbers_in(body) - numbers_in(source_text(cited))
        if missing:
            return False, f"number not in cited articles: {', '.join(sorted(missing))}"

    english = all((a.get("lang") or "en") == "en" for a in cited)
    if c.get("check_names", True) and english:                                 # check 4
        names = names_in(body)
        if names:
            found = [n for n in names if plain(n).strip("'’") in src_plain]
            if len(found) / len(names) < c.get("name_match_min", 0.7):
                return False, f"names not in cited articles: {', '.join(sorted(set(names) - set(found)))}"

    if c.get("check_wording", True) and english:                               # check 5
        verbs = {w for v in c.get("reporting_verbs", []) for w in v.split()}
        words = [w for w in content_words(body, verbs) if not w.isdigit() and w not in NUMBER_WORDS]
        source_stems = {stem(w) for w in content_words(source_text(cited), set())}
        if words:
            missing = [w for w in words if stem(w) not in source_stems]
            if 1 - len(missing) / len(words) < c.get("wording_match_min", 0.65):
                return False, f"wording not from cited articles: {', '.join(missing[:6])}"

    for w in c.get("analysis_words", []):                                      # check 6
        # lowercase match only, so "May" the month isn't caught; allowed if the source used the word
        if re.search(rf"\b{re.escape(w)}\b", body) and not re.search(rf"\b{re.escape(plain(w))}\b", src_plain):
            return False, f"analysis word not used by the source: '{w}'"

    return True, ""


# ── Built-in examples: run `python pipeline/guardrails.py` ───────────────────
if __name__ == "__main__":
    # Fictional examples: a made-up country (Norland), port and party, so nothing here is real news.
    art = {"title": "Four cargo ships damaged by sea mines near Port Elm, Norland coast guard says",
           "summary": "The coast guard said the ships were still on fire, and two other vessels had been detained.",
           "lang": "en"}
    pl = {"title": "Strzelanina w Lindau: nie żyje 6 osób", "summary": "", "lang": "pl"}
    vote = {"title": "Norland election: Unity Party vote share falls with 80 percent of ballots counted",
            "summary": "The party faces a heavy defeat in the regional vote.", "lang": "en"}
    examples = [
        ("faithful restatement", "[1] reported that with 80 percent of ballots counted, the Unity Party's vote share fell.", [vote]),
        ("check 5, AI's own conclusion", "[1] reported the Unity Party faces a defeat that will permanently alter the political landscape.", [vote]),
        ("faithful restatement", "[1] reported the Norland coast guard said four cargo ships were damaged by sea mines near Port Elm.", [art]),
        ("check 1, no source", "Sea mines damaged four cargo ships near Port Elm.", [art]),
        ("check 2, stated as fact", "Cargo ships hit mines near Port Elm [1].", [art]),
        ("check 3, wrong number", "[1] reported that six cargo ships hit mines near Port Elm.", [art]),
        ("check 3, wrong number", "[1] reported 5 ships were damaged near Port Elm.", [art]),
        ("check 4, invented actor", "[1] reported that the navy of Estria condemned the attack near Port Elm.", [art]),
        ("check 6, AI's own judgment", "[1] reported the coast guard said four ships damaged by sea mines could still be on fire.", [art]),
        ("translated source, right number", "[1] reported that 6 people died in a shooting in Lindau.", [pl]),
        ("translated source, wrong number", "[1] reported that 7 people died in a shooting in Lindau.", [pl]),
    ]
    for label, sentence, cited in examples:
        ok, why = check(sentence, cited)
        print(f"{'KEEP  ' if ok else 'REJECT'}  ({label})\n        {sentence}" + ("" if ok else f"\n        -> {why}"))
