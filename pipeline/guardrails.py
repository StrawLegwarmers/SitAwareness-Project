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
from decimal import Decimal, InvalidOperation

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
Defense Defence Interior Foreign Affairs Justice Health Finance Economy Trade Transport Infrastructure Education
Energy Labour Labor Agriculture Environment Security Council Committee Commission Department Agency Office
Navy Air Force Forces Guard Coast Border Ministers Deputy Vice Speaker Senator Governor Mayor Ambassador
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
                     "eighty": "80", "ninety": "90", "dozen": "12", "hundred": "100"})
NUMBER_WORDS.pop("one")  # "one of the..." is too common to treat as a count

# Small numbers in the other languages of the feeds, 2 to 12 and 20. Used only on the text of a
# NON-English cited article, so the AI's "two cars" can be checked against Russian "две машины".
_FOREIGN = {
    2: "dos dois duas deux zwei due twee två dwa dwie dwóch два две двое двух дві dva dvije dve iki",
    3: "tres três trois drei tre drie trzy trzech три трое трех трёх tri üç",
    4: "cuatro quatro quatre vier quattro fyra cztery четыре четырех чотири четири četiri dört",
    5: "cinco cinq fünf cinque vijf fem pięć пять пяти пет pet beş",
    6: "seis six sechs sei zes sex sześć шесть шести шість шест šest altı",
    7: "siete sete sept sieben sette zeven sju siedem семь сім седем sedam yedi",
    8: "ocho oito huit acht otto åtta osiem восемь вісім осем osam sekiz",
    9: "nueve nove neuf neun negen nio dziewięć девять дев'ять девет devet dokuz",
    10: "diez dez dix zehn dieci tien tio dziesięć десять десет deset",
    11: "once onze elf undici elva",
    12: "doce doze douze zwölf dodici twaalf tolv",
    20: "veinte vinte vingt zwanzig venti twintig tjugo yirmi",
}
FOREIGN_NUMBER_WORDS = {unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode() or w: str(n)
                        for n, words in _FOREIGN.items() for w in words.split()}
FOREIGN_NUMBER_WORDS.update({w: str(n) for n, words in _FOREIGN.items() for w in words.split()})

# "15 thousand", "1.5 million", "$3bn", "15 bin" (Turkish), "2 тыс." -> one number, multiplied out,
# so "15,000" in a report matches "15 thousand" (or "15 mil", "15 тысяч") in its source.
MULTIPLIERS = {}
for _value, _words in ((10**3, "thousand thousands mil mille mila tausend tys tysiecy tysiace tysięcy tysiące тысяч тысячи тысяча тыс "
                                "хиляди хиляда hiljada hiljade tisuca tisuća bin duizend tusen"),
                       (10**6, "million millions mn mln millon millón millones milhao milhão milhoes milhões milione milioni "
                                "millionen mio milion miliony milionow milionów миллион миллиона миллионов млн милиона "
                                "милион miliona milyon miljoen miljon miljoner"),
                       (10**9, "billion billions bn milliard milliards miliardo miliardi milliarde milliarden mrd miliard "
                                "miliardy miliardow miliardów миллиард миллиарда миллиардов млрд милиарда milijarda milijardi "
                                "milyar miljard bilhao bilhão bilhoes bilhões"),
                       (10**12, "trillion trillions tn")):
    for _w in _words.split():
        MULTIPLIERS[_w] = _value
CURRENCY_SUFFIX = {"k": 10**3, "m": 10**6, "b": 10**9}       # "$2m", "£3b": only straight after a currency sign

_NUM_TOKEN = re.compile(r"([$£€¥]?)(?<![\d.,])(\d+(?:[.,]\d+)*)([a-zA-Z]{0,3})|([^\W\d_][\w'’]*)", re.U)


def _decimal(m: str) -> Decimal | None:
    """'1,200' -> 1200, '6.3' -> 6.3, '1,5' (decimal comma) -> 1.5, '1.200.000' -> 1200000."""
    if re.fullmatch(r"\d{1,3}([,.]\d{3})+", m) and not re.fullmatch(r"\d{1,3}[.]\d{3}", m):
        m = re.sub(r"[,.]", "", m)            # thousands separators (one "1.200" stays ambiguous: read as 1.2)
    try:
        return Decimal(m.replace(",", "."))
    except InvalidOperation:
        return None


def _fmt(d: Decimal) -> str:
    out = format(d.normalize(), "f")
    return out.rstrip("0").rstrip(".") if "." in out else out


def numbers_in(text: str, foreign: bool = False) -> set[str]:
    """
    '$6.3bn', '1,200 people', '80%', 'four tankers', '15 thousand' -> {'6300000000', '1200', '80', '4', '15000'}
    foreign=True also reads small numbers written as words in other languages (for a cited article
    that isn't in English).
    """
    out, pending = set(), None              # pending: a number waiting to see if a multiplier follows
    words = {**NUMBER_WORDS, **(FOREIGN_NUMBER_WORDS if foreign else {})}

    def flush():
        nonlocal pending
        if pending is not None:
            out.add(_fmt(pending))
        pending = None

    for m in _NUM_TOKEN.finditer(text or ""):
        cur, digits, suffix, word = m.group(1), m.group(2), (m.group(3) or "").lower(), m.group(4)
        if digits:
            flush()
            value = _decimal(digits)
            if value is None:
                continue
            if foreign and re.fullmatch(r"\d{1,3}\.\d{3}", digits):
                out.add(digits.replace(".", ""))            # "1.200" is 1,200 in most other languages
            if suffix in MULTIPLIERS:                       # "6.3bn", "2mln"
                value *= MULTIPLIERS[suffix]
            elif cur and suffix in CURRENCY_SUFFIX:         # "$2m"
                value *= CURRENCY_SUFFIX[suffix]
            pending = value
            continue
        w = plain(word).strip("'’.")
        if pending is not None and w in MULTIPLIERS:
            pending *= MULTIPLIERS[w]                       # "15 thousand", "3 mil millones"
            continue
        flush()
        if w in words:
            pending = Decimal(words[w])
    flush()
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


def source_numbers(articles: list[dict]) -> set[str]:
    """Every number in the cited articles, reading number words in each article's own language."""
    out = set()
    for a in articles:
        out |= numbers_in(f"{a.get('title', '')} {a.get('summary', '')}", foreign=(a.get("lang") or "en") != "en")
    return out


def _places():
    """countries.py, for recognising countries, demonyms, cities and people in any language (geo config)."""
    try:
        import countries
        return countries.load("geo")
    except Exception:                 # the checks must work even without the geography files
        return None


# "[7], a Russian state outlet, reported ...": a description of the OUTLET, which the prompt asks for.
# Left out of the name and country checks, since the article itself rarely says where its outlet is.
APPOSITIVE = re.compile(r"((?:\[\d+(?:\s*,\s*\d+)*\]\s*)+),\s*(?:an?|the)\s[^,]{1,80},", re.I)


def check(sentence: str, cited: list[dict]) -> tuple[bool, str]:
    c = cfg()
    if not CITE.search(sentence or "") or not cited:
        return False, "no citation"                                            # check 1
    body = CITE.sub(" ", sentence)
    about = CITE.sub(" ", APPOSITIVE.sub(r"\1", sentence))     # the sentence minus "a Russian state outlet"
    body_plain, src_plain = plain(body), plain(source_text(cited))

    if len(body.split()) > c.get("max_words", 45):
        return False, f"too long ({len(body.split())} words)"

    verbs = c.get("reporting_verbs", [])
    if not any(re.search(rf"\b{re.escape(v)}\b", body_plain) for v in verbs):
        return False, "not attributed (no reporting verb)"                     # check 2

    if c.get("check_numbers", True):                                           # check 3
        missing = numbers_in(body) - source_numbers(cited)
        if missing:
            return False, f"number not in cited articles: {', '.join(sorted(missing))}"

    english = all((a.get("lang") or "en") == "en" for a in cited)
    if c.get("check_names", True):                                             # check 4
        # A country, demonym, city or person known to countries.py counts as found when the cited
        # articles name the same country in ANY language ("Chinese" ~ "China", "Spain" ~ "España").
        # For translated sources, only those names can be checked; for English ones, all names are.
        g = _places()
        src_countries = set(g.find(source_text(cited))) if g else set()

        def found(name):
            cid = g.lookup(name) if g else None
            return plain(name).strip("'’") in src_plain or bool(cid and cid in src_countries)
        names = sorted(names_in(about))
        if english and names:
            ok = [n for n in names if found(n)]
            if len(ok) / len(names) < c.get("name_match_min", 0.7):
                return False, f"names not in cited articles: {', '.join(n for n in names if n not in ok)}"
        elif not english and g and src_countries:
            # Translated sources: people's names are spelled differently in other scripts, so only a
            # clear contradiction is caught: the sentence's countries and the article's countries
            # have nothing in common (the AI put the story in the wrong country).
            mine = {cid for cid, w in g.find(about).items() if w >= 0.5}
            if mine and not mine & src_countries:
                return False, f"countries not in cited articles: {', '.join(sorted(mine))}"

    if c.get("check_wording", True) and english:                               # check 5
        verbs = {w for v in c.get("reporting_verbs", []) for w in v.split()}
        words = [w for w in content_words(about, verbs) if not w.isdigit() and w not in NUMBER_WORDS]
        source_stems = {stem(w) for w in content_words(source_text(cited), set())}
        g = _places()
        src_countries = set(g.find(source_text(cited))) if g else set()

        def in_source(w):        # "chinese" counts when the article says "China"
            cid = g.lookup(w.capitalize()) if g else None
            return stem(w) in source_stems or bool(cid and cid in src_countries)
        if words:
            missing = [w for w in words if not in_source(w)]
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
        ("translated source, number word", "[1] reported that two cars caught fire in Moscow.",
         [{"title": "В Москве загорелись две машины", "summary": "", "lang": "ru"}]),
        ("translated source, wrong country", "[1] reported that Polish police arrested two men in Warsaw.",
         [{"title": "В Москве задержали двух мужчин", "summary": "", "lang": "ru"}]),
        ("thousands written out", "[1] reported that 15,000 soldiers were sent.",
         [{"title": "15 bin asker gönderildi", "summary": "", "lang": "tr"}]),
    ]
    for label, sentence, cited in examples:
        ok, why = check(sentence, cited)
        print(f"{'KEEP  ' if ok else 'REJECT'}  ({label})\n        {sentence}" + ("" if ok else f"\n        -> {why}"))
