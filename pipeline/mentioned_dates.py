"""
mentioned_dates.py - dates written in a headline or summary, turned into real dates. No AI.

  python pipeline/mentioned_dates.py "Talks resumed on 8 November after a pause" 2026-11-12T08:00:00+00:00

A story is often picked up a day or two late, so the day an outlet PUBLISHED isn't always the day
something HAPPENED. When an article states a date, this finds it, so the website can show the
dates the reporting mentions, counted by outlet ("Sat 8 Nov (3 outlets)").

Deliberately strict, to avoid wrong dates:
  - only explicit dates ("8 November", "Nov. 8", "8 de noviembre") and "yesterday"
  - weekday names ("on Saturday") are ignored: "talks will resume on Saturday" is the future
  - a date must fall in the two weeks up to the day the article was published; anything else
    (a future date, an anniversary) is dropped
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta

MONTHS = {
    # English
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    # Spanish, Portuguese, French, German, Italian
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "janeiro": 1, "fevereiro": 2, "março": 3, "maio": 5, "junho": 6, "julho": 7, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "décembre": 12,
    "januar": 1, "februar": 2, "märz": 3, "juni": 6, "juli": 7, "oktober": 10, "dezember": 12,
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "settembre": 9,
    "ottobre": 10, "dicembre": 12,
}
_M = "|".join(sorted(MONTHS, key=len, reverse=True))
DAY_MONTH = re.compile(rf"(?<![\d.:/])(\d{{1,2}})(?:st|nd|rd|th|er|º)?\.?\s+(?:of\s+|de\s+)?({_M})\b\.?(?:,?\s+(?:de\s+)?(\d{{4}}))?", re.I)
MONTH_DAY = re.compile(rf"\b({_M})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?![\d:])", re.I)
YESTERDAY = re.compile(r"\b(yesterday|ayer|ontem|gestern|ieri)\b", re.I)
LOOKBACK_DAYS = 14


def dates_in(text: str, published: str) -> list[str]:
    """ISO dates mentioned in the text, resolved against the article's publication time."""
    try:
        pub = datetime.fromisoformat(published).date()
    except (TypeError, ValueError):
        return []
    found = set()
    for day, month, year in [(m.group(1), m.group(2), m.group(3)) for m in DAY_MONTH.finditer(text or "")] + \
                            [(m.group(2), m.group(1), m.group(3)) for m in MONTH_DAY.finditer(text or "")]:
        if month.lower() in ("may", "mar") and month[0].islower():
            continue                         # "may" the verb, "mar" (Spanish: sea)
        d = _resolve(int(day), MONTHS[month.lower()], pub)
        if d and (not year or int(year) == d.year):     # "8 November 2025" in 2026 is an anniversary
            found.add(d)
    if YESTERDAY.search(text or ""):
        found.add(pub - timedelta(days=1))
    ok = {d for d in found if d and pub - timedelta(days=LOOKBACK_DAYS) <= d <= pub}
    return sorted(d.isoformat() for d in ok)


def _resolve(day: int, month: int, pub: date) -> date | None:
    """The year isn't written: take the publication year, or the year before for a December date in January."""
    for year in (pub.year, pub.year - 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d <= pub:
            return d
    return None


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "Russia and Ukraine swapped prisoners on Nov. 8; talks resume on 20 November"
    pub = sys.argv[2] if len(sys.argv) > 2 else datetime.now().isoformat()
    print(dates_in(text, pub))
