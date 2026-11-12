# Geography

Geopolitical stories are filed by the countries they are **about**, not by where the reporting
outlets are based. No AI decides this: `pipeline/countries.py` counts names, using
`config/geo/countries.yaml` (about 180 countries), `config/geo/country_names.yaml` (names in other
languages) and `config/geo/entities.yaml` (cities, institutions, people and companies).

```bash
python pipeline/countries.py "Coalition talks resume in Warsaw"   # test a headline
python pipeline/countries.py --stories                            # where every tracked story goes, and why
```

## Placing a story

For each story, country mentions are counted in its title (counted double), its reports and its
headlines. Then:

- **Countries**: those named in the title first, then any other country with at least a quarter of
  the top country's mentions (and more than a passing mention). Up to five.
- **Lead country**, the one it is mainly about: a title that starts with a country and a colon
  ("Poland: …"); otherwise the AI's `country` for the story, *only if* the story's own headlines name
  that country; otherwise the title's most-mentioned country (the first named breaks a tie).
- **Region**, in this order:
  1. the region holding *more than half* of the mentions;
  2. if none does: **Global** when the countries span three or more regions (a summit), otherwise
     the lead country's region ("France summons Iran's envoy" goes to Europe);
  3. no country named at all: the region of its outlets when two thirds come from one region (local
     news, "Police chief sacked over kidnappings"), otherwise **Global**.
- **Domestic or international**: one country, or several. Shown on every card.
- Your `place:` rules in `corrections.yaml` override all of the above.

`countries.py --stories` prints the rule that decided each story, so a misplaced one is easy to
trace and fix.

Refinements that keep placement honest:

- **Venues.** Cities that often host talks about other countries (`venues:`) count a quarter, so
  "talks in [host city]" doesn't make the host the subject.
- **Not countries.** Phrases containing a country word that aren't about it ("Latin American",
  newspaper names, sports clubs) are removed first (`not_countries:`). Matching is case-sensitive,
  so "US" never matches "us". A name that is ambiguous on its own (Georgia) can be marked
  `ambiguous: true`, so only its other words count.
- **Hyphens** separate names: "Russia-US-Ukraine talks", "Saudi-led", "Kyiv-based".

## Entities

`entities.yaml` lists names that point to a country without naming it, so "Nvidia boss questioned
by FBI" is placed in the United States:

| Heading | Examples | Weight |
|---|---|---|
| `places` | New York City, California, Kharkiv, Shanghai | 1 |
| `institutions` | FBI, Bundeswehr, Knesset, Hamas | 1 |
| `people` | political figures, in office or not (a former leader still belongs to the same country) | 1 |
| `companies` | by headquarters: Nvidia, TSMC, Gazprom | ½, so "EU fines a US company" leans to the side taking action |

Leave out names that also mean something else ("Nice", "Amazon" the river). When an entity misleads
placement, delete it, or fix the one story with `place:` in `corrections.yaml`.

## Reach and the Global page

**Reach** is how many source regions' outlets reported a story: six regions plus international
outlets, so 1 to 7. It is counted from the outlets, not judged, and shown on each card.

The Global page opens with **Reported worldwide**: up to 12 stories with coverage from at least
three regions, widest reach first, then most outlets. These are the stories the whole world is
reporting, wherever they happened; each also stays on the page of the region it is about. Below
come the stories filed under Global itself (no single region, or no country named).

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

A country is a **hotspot** when it has at least 8 headlines in the last 24 hours *and* at least twice
its usual **share** of all headlines. The usual share comes from the previous seven days, using only
full days of collection (a day with less than 60% of the busiest day's headlines was a partial
download, and would make every country look busy). Comparing shares rather than counts means adding
sources doesn't turn every country into a hotspot. The badge needs three full days of history.

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
