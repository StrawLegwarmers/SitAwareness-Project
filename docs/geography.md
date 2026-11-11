# Geography

Geopolitical stories are filed by the countries they are **about**, not by where the reporting
outlets are based. No AI is involved: `pipeline/countries.py` counts country names, using
`config/geo/countries.yaml` (about 180 countries) and `config/geo/country_names.yaml` (names in other
languages).

```bash
python pipeline/countries.py "Coalition talks resume in Warsaw"   # test a headline
python pipeline/countries.py --stories                            # where every tracked story goes, and why
```

## Placing a story

For each story, country mentions are counted in its title (counted double), its reports and its
headlines. Then:

- **Countries**: those named in the title first, then any other country with at least a quarter of
  the top country's mentions (and more than a passing mention). Up to five.
- **Region**: the region holding *more than half* of those countries' mentions. If no region does
  (a summit, trade between two continents), the story goes on **Global**. A title starting with a
  country and a colon ("Poland: …") settles it.
- **Domestic or international**: one country, or several. Shown on every card.

Two refinements keep placement honest:

- **Venues.** Cities that often host talks about other countries (`venues:`) count a quarter, so
  "talks in [host city]" doesn't make the host the subject.
- **Not countries.** Phrases containing a country word that aren't about it ("Latin American",
  newspaper names, sports clubs) are removed first (`not_countries:`). Matching is case-sensitive,
  so "US" never matches "us". A name that is ambiguous on its own (Georgia) can be marked
  `ambiguous: true`, so only its other words count.

## Region pages

Each region page has a block per country, ordered by regional tier, then by stories with new
reporting, then by headline volume:

- The country's **stories**, with new reporting first and quiet ones folded.
- **Other headlines mentioning the country**: news headlines from every feed that aren't part of a
  story yet. Up to 25 per country, from the last 24 hours (or the whole catch-up window). They are
  stored in a separate file per day and downloaded only when a region page is opened or a search runs.
- Then **more countries** (mentioned, no story yet), **stories involving the region** that sit on
  other pages, and **opinion and analysis** pieces filed by the countries in their headline.

## Tiers

Every country has two tiers, from 1 (most relevant) to 3, set by the analyst:

```yaml
- {id: poland, name: Poland, region: europe, global: 2, regional: 1, also: [Polish, Warsaw]}
```

| Tier | Effect |
|---|---|
| `regional: 1` | Always has a block on its region page, even on a quiet day ("No story with new reporting today") |
| `regional` | Orders the region page |
| `global` | Orders "Countries in the news" on the Overview; tier 1 shown in bold |

Tiers change order and visibility only. They never hide reporting, change counts, or reach the AI.

## Hotspots

A country is a **hotspot** when it has at least 8 headlines in the last 24 hours *and* at least
twice its daily average over the previous week. The badge needs about four days of history in the
database before it can appear.

## Other languages

About half of the geopolitical headlines are not in English. `country_names.yaml` adds names in 16
language groups (Spanish, Portuguese, French, German, Italian, Dutch, Swedish, Polish, Turkish,
Russian, Ukrainian, Bulgarian, Serbian/Bosnian/Croatian, Kazakh, Chinese, Arabic):

- **Word endings**: `Name*` matches any ending, for languages that change the end of names
  (Russian Испания, Испании, Испанию; German Russland, Russlands).
- **Chinese** names match anywhere in a headline, since Chinese has no spaces between words.
- **Arabic** names may follow the one-letter prefixes و ب ل ف ك ("and", "in", "for"…).

On a sample of 6,808 news headlines, those linked to a country rose from 2,586 to 3,005, without adding
wrong matches to English headlines. Many local headlines never name a country, so full coverage isn't expected.
Add names to the file when you notice gaps.
