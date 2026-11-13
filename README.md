# Situational Awareness Project

An open-source collection tool for geopolitical and cyber threat analysts. Every morning it reads
about 330 public RSS feeds, groups the articles into running **stories**, and publishes a daily brief
as a static website, plus feeds that threat-intelligence platforms such as OpenCTI can ingest.

It reports what outlets **reported**, nothing more. Code groups the headlines that report the same
event; an AI model only checks each group and restates single reported facts with a citation; code
checks every sentence against the article it cites, removes what doesn't match, and dates it by its
source's publication. A late outlet repeating known facts is shown as corroboration, not news.
Opinion and analysis pieces are labelled and kept apart from reporting. Rankings are counted
(regions and outlets reporting a story), never judged. Each story is titled with the day's lead
headline, picked by code from what most outlets reported, under the name of the wider story it
belongs to.

## What you get

- **Geopolitical**: an overview (bottom line up front, most reported stories, countries in the news)
  and one page per region: Global (the stories reported worldwide), Europe, North America, Asia &
  Pacific, Middle East & North Africa, Latin America & Caribbean, Africa. Stories are filed by the
  countries they are about, with analyst-set country tiers and activity hotspots.
- **Markets**: market and company stories, official rates and prices (Treasury, New York Fed, ECB,
  EIA), the next 7 days (central bank decisions, US data releases, Treasury auctions), SEC 8-K
  filings by listed companies, central bank releases and labelled analysis. Not investment advice.
- **Cyber**: the daily brief, industry intelligence for ten sectors, exploited vulnerabilities
  (CISA KEV and CVEs in the news), indicators of compromise from vendor research, vendor research
  and cyber news headlines.
- **Reference**: an OSINT toolkit, the health of every source (with add and change requests from the
  browser), and instructions for connecting OpenCTI.
- **Any period**: pick one day, or combine up to 14 days into a single view; search the last 30 days.
- **Yours**: a watchlist of words you follow, kept in your browser only; a compact list view; copy
  any story with its sources.
- **Machine feeds**: RSS of stories, CSV of indicators and vulnerabilities, and a STIX 2.1 bundle.

## How it works

```
 config/*.yaml          pipeline/ (Python, runs daily on GitHub Actions)              site/ (GitHub Pages)
┌──────────────┐   ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌──────────┐   ┌──────────────────┐
│ sources,     │──▶│  fetch   │──▶│  store   │──▶│ narratives │──▶│  export  │──▶│ website + feeds  │
│ countries,   │   │ RSS, tag │   │ SQLite,  │   │code groups,│   │ daily    │   │ static HTML + JS │
│ industries   │   │ opinion  │   │ dedupe   │   │AI restates,│   │ JSON,RSS │   │ reads the JSON   │
│              │   │          │   │          │   │code checks │   │          │   │                  │
└──────────────┘   └──────────┘   └──────────┘   └────────────┘   └──────────┘   └──────────────────┘
```

Each layer talks to the next only through files: configuration is YAML, the pipeline writes JSON,
the website reads JSON. The website is plain HTML and JavaScript with no server and no keys.

## Quick start

```bash
pip install -r requirements.txt
python pipeline/check_sources.py                 # test every feed
python pipeline/fetch.py                         # download the latest articles
python pipeline/indicators.py                    # CISA KEV and indicators of compromise
python pipeline/markets_data.py                  # official rates, calendar, SEC filings (Markets)
AI_PROVIDER=mock python pipeline/narratives.py   # group stories without an AI key (test mode)
python pipeline/export.py                        # write the website's data and feeds
python -m http.server --directory site 8000      # open http://localhost:8000
```

For daily automated runs on GitHub (free for public repositories), see
[docs/operations.md](docs/operations.md).

Tests need no key and no network: `pip install -r requirements-dev.txt`, then `python -m pytest -q`.
They also run on GitHub on every push.

## Documentation

| Document | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | The pipeline step by step, and where every file lives |
| [Configuration](docs/configuration.md) | Every configuration file and setting |
| [Sources](docs/sources.md) | Source format, finding feeds, the Sources page, adding sources from the browser |
| [Collection](docs/collection.md) | Fetching, storage, duplicates, opinion and analysis |
| [Stories and guardrails](docs/stories.md) | How stories are grouped, what the checks do, corrections |
| [Geography](docs/geography.md) | Countries, regions, tiers, hotspots, other languages |
| [Cyber](docs/cyber.md) | Exploited vulnerabilities, indicators of compromise, industries |
| [Markets](docs/markets.md) | Market stories, official rates, the calendar, SEC filings |
| [Website](docs/website.md) | Pages, the calendar and date ranges, search, security |
| [Feeds and OpenCTI](docs/feeds-and-opencti.md) | RSS, CSV and STIX outputs, and OpenCTI setup |
| [Operations](docs/operations.md) | Daily automation, keys, limits, retention, troubleshooting |

## Folder map

| Path | What's in it |
|---|---|
| `config/<site>/sources.yaml` | The feeds, per site (`geo`, `cyber`, `markets`) |
| `config/<site>/site.yaml` | AI focus, story groups, headline lists, sidebar pages, retention |
| `config/geo/countries.yaml`, `country_names.yaml` | Countries, regions, tiers, names in other languages |
| `config/geo/corrections.yaml` | Manual fixes when grouping goes wrong |
| `config/cyber/industries.yaml` | Industry keyword lists |
| `config/markets/calendar.yaml` | Central bank decision dates for the Markets calendar |
| `config/content_types.yaml` | How opinion, analysis and off-topic sections are recognised |
| `config/geo/entities.yaml` | Cities, institutions, people and companies that point to a country |
| `config/guardrails.yaml`, `config/prompts/` | The checks and the AI instructions |
| `config/feeds.yaml` | RSS, CSV and STIX outputs |
| `pipeline/` | The Python pipeline |
| `site/` | The website (and its daily data in `site/data/`) |
| `state/` | Stories being tracked, and the audit log of removed sentences |
| `.github/` | The daily, tests, maintenance and source-request workflows, Dependabot, and the source forms |
| `tests/` | Automated tests (`python -m pytest -q`) |

## Licence

The code and configuration are released under the [MIT licence](LICENSE). Headlines, article links
and the material they point to belong to their publishers; see [NOTICE.md](NOTICE.md).
