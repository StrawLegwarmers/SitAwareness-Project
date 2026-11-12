# Collection

`pipeline/fetch.py` downloads every enabled feed and stores new articles in `data/sitaware.db`
(SQLite). Running it twice in a row adds almost nothing the second time, so it is always safe to
re-run.

## Downloading

- **Sixteen feeds at a time,** each with a 20-second timeout and a 15 MB size limit (a bigger
  response is a mistake or an attack, and is stopped while downloading).
- **Conditional requests.** Each feed's `ETag` and `Last-Modified` are remembered; an unchanged feed
  answers "not modified" and nothing is downloaded.
- **Three-day window.** Items older than three days are ignored, so a feed that carries months of
  archive doesn't flood the first run.
- **Failures are recorded, not fatal.** A failing feed is logged with its error and a count of
  failures in a row (shown on the Sources page); the other feeds carry on. A valid feed that simply
  has no items today counts as working (quiet), not failing.

## Cleaning each item

`pipeline/normalize.py` turns every feed's quirks into one record:

- HTML is stripped from summaries, which are cut at 500 characters.
- Links are reduced to a **canonical address**: lower-case host, `https`, tracking parameters
  (`utm_*`, `traffic_source` and similar) and fragments removed. Only `http` and `https` links are
  accepted, so a malicious `javascript:` link can never be stored.
- Google News search items are unwrapped to the real publisher and headline.
- Missing dates become the time first seen; future dates are clamped to now.
- Each item is labelled **news, opinion or analysis** (below).

## Duplicates

Duplicates are caught at several layers, from cheapest to most careful:

| Layer | Rule |
|---|---|
| Same address | One article per canonical address per site |
| Same headline | The same headline (letters and digits only) on the same site within 3 days is a re-post, skipped |
| Same organisation | Feeds of one publisher count as one outlet (`config/publishers.yaml`) |
| Same story | A "new" story that matches one already tracked is merged into it ([stories](stories.md#duplicates)) |
| Same report | A report nearly identical to one already in the story is skipped |

## Opinion and analysis

An op-ed restated as "Outlet X reported that…" would present opinion as fact, and would pass every
sentence check, because the sentence does match its article. So articles are labelled before
anything else, using the outlet's **own** labels (`config/content_types.yaml`), first match wins:

1. The source's `kind` in `sources.yaml`.
2. The item's RSS categories: the whole category must match ("Opinion", "Editorial", "Analysis"…),
   so a subject tag such as "Polls and public opinion" doesn't count. If an item is tagged both
   "News" and "Opinion", its categories are ignored.
3. A folder in its address: `/opinion/`, `/commentisfree/`, `/editorial/`, `/analysis/`, and their
   equivalents in other languages (`/opinion/`, `/colunas/`, `/meinung/`, `/idees/`…). The last part
   of the address (the article's own name) is never used.
4. Its headline: "Analysis:", "Opinion |", "… - opinion", "The [newspaper] view on …".
5. Its source type: think tanks publish analysis.

On a day of 8,300 articles this labelled about 3% (188 opinion pieces from 51 sources, 94 analysis
pieces from 19 sources). See today's labels with `python pipeline/content.py`.

| | News | Opinion and analysis |
|---|---|---|
| Sent to the AI | Yes | Never |
| Can be cited in a report | Yes | Never |
| Counts as an outlet reporting a story | Yes | No |
| Shown on the website | In stories | In an "Opinion and analysis" block, labelled, filed by the countries in its headline |

To treat a whole source differently, add `kind: news` (or `opinion`, `analysis`) to its line.

## Off-topic sections

General news sites also publish sport, entertainment, celebrity, lifestyle and property sections.
On the Geopolitical site these are labelled **off-topic** the same way (RSS category or address
folder: `/sport/`, `/deportes/`, `/entertainment/`, `/espectaculos/`, `/lifestyle/`…; listed under
`offtopic:` in `content_types.yaml`) and checked first. Off-topic articles stay in the database but
are never sent to the AI, never counted and never shown. Measured on 13,000 stored articles: 658
off-topic, mostly sport. Folders that also carry hard news (culture, arts, travel, people, tv, autos)
are deliberately not on the list.

When the labels change, the database relabels its stored articles once, by itself (a version number
inside the database file records which labels it has).

## The database

| Table | Contents |
|---|---|
| `articles` | Every article from the last 30 days: source, outlet, address, headline, summary, dates, region or section, type, language, kind |
| `forgotten` | Ids of articles deleted after 30 days, kept 120 days. Some feeds keep undated items for months; without this they would come back as "new" |
| `feed_state` | Per feed: ETag, Last-Modified, last success, last error, failures in a row |
| `fetch_log` | One row per feed per run |
| `kev` | The CISA Known Exploited Vulnerabilities catalog |
| `iocs` | Indicators of compromise (always stored defanged) |
| `ioc_pages` | Research pages already scanned for indicators |

Look inside with:

```bash
python pipeline/stats.py                      # overview per site and source
python pipeline/stats.py --search "ceasefire"  # headlines containing a word
python pipeline/sql.py "SELECT lang, COUNT(*) FROM articles GROUP BY lang ORDER BY 2 DESC"
```

Articles older than 30 days are deleted at the end of each run. An older database gains any new
columns automatically the next time it is opened.
