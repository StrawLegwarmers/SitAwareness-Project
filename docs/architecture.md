# Architecture

The project is a pipeline of small Python scripts that run once a day, and a static website that
reads what they produce. Nothing runs between those daily runs: there is no server, no database
service and no API key in the website.

## The daily run

| Step | Script | What it does | Writes |
|---|---|---|---|
| 1 | `fetch.py` | Downloads every enabled feed (16 at a time), cleans each item, labels it news, opinion or analysis, skips duplicates | `data/sitaware.db` |
| 2 | `indicators.py` | Downloads the CISA Known Exploited Vulnerabilities catalog and collects indicators of compromise | `data/sitaware.db` |
| 3 | `narratives.py` | Groups the new news headlines by event in code (`cluster.py`), sends the groups to the AI, which checks them and writes attributed one-sentence reports; code checks every sentence, dates it and records corroboration | `state/<site>/narratives.json`, `state/<site>/audit.json` |
| 4 | `export.py` | Builds the day's brief for the website: placement by country, rankings, industries, vulnerabilities, indicators, opinion pieces, the Sources page; then the machine feeds | `site/data/`, `site/feeds/` |
| 5 | GitHub Actions | Commits `state/` and `site/data/`, then publishes `site/` to GitHub Pages | |

`.github/workflows/daily.yml` runs these steps every morning. See [operations](operations.md).

## Where things live

| Location | What | Kept in Git? |
|---|---|---|
| `config/` | Everything you can change: sources, countries, industries, pages, checks, prompts | Yes |
| `data/sitaware.db` | Working memory: every article from the last 30 days, feed status, vulnerabilities, indicators | No. Carried between runs by the GitHub Actions cache, and rebuilt from the feeds if lost |
| `state/<site>/narratives.json` | The stories being tracked, with their articles and checked reports | Yes |
| `state/<site>/audit.json` | Every sentence the checks removed in the last 7 days, and why | Yes |
| `site/data/<site>/<date>.json` | One day's brief, exactly as it was published | Yes (last 12 months) |
| `site/data/<site>/headlines/<date>.json` | Per-country headlines for that day | Yes (last 12 months) |
| `site/data/cyber/iocs-<date>.csv` | That day's indicators, defanged | Yes (last 12 months) |
| `site/data/index.json`, `sources.json`, `toolkit.json` | Available dates, source health, toolkit links | Yes |
| `site/data/<site>/search-index.json` | The stories of the last 30 briefs, a few fields each, for searching earlier days | Yes |
| `site/feeds/` | RSS, CSV and STIX for other tools; indicators in real (refanged) form | No: rebuilt every run and published only |

## The data contract

The website never touches the database or the state files. It reads only what `export.py` writes
into `site/data/`. A daily file contains:

| Key | Contents |
|---|---|
| `stories` | Each story: title, region, countries, status, outlet counts, reach (source regions), checked reports with links, publication dates and corroborating outlets, dates mentioned, original headlines |
| `bluf`, `top`, `worldwide` | The bottom line up front, the most reported stories, and the stories reported in the most regions, taken from checked reports |
| `pages` | The sidebar for that site, and which blocks each page shows |
| `countries`, `headlines` | Per-country counts, tiers and hotspots, and the file holding their headlines |
| `commentary` | Opinion and analysis pieces, labelled |
| `lists`, `industries`, `vulns`, `iocs` | Headline lists, industry matches, exploited vulnerabilities, indicators |
| `stats`, `window` | Sources read, reports written, sentences removed, collection numbers (`coverage`); the period the brief covers |

Each daily file is a snapshot: the next run writes a new file and leaves it alone, so any past day
can be shown exactly as it was, and several days can be merged in the browser.

## Design principles

- **Collect, don't conclude.** Code groups; the AI checks the groups and restates; it never assesses, predicts or explains.
- **Every sentence has a source,** checked by code against that source, with the link inserted by
  code (the AI never writes web addresses).
- **Counted, not judged.** Importance is how many regions' outlets, and how many distinct outlets, reported a story.
- **Original headlines are always shown** next to the AI's sentences.
- **Configuration over code.** Sources, countries, tiers, industries, pages and checks are YAML.
- **No secrets in the website.** Keys live only in GitHub's encrypted secrets and are used during
  the daily run.
