# Configuration

Everything that changes how the tool behaves is a YAML file in `config/`. A typo stops the run with
a message naming the file and line. Run `python pipeline/check_sources.py` after editing sources, and
`python pipeline/export.py` after editing pages, countries or industries, to see the effect.

## Per site: `config/geo/` and `config/cyber/`

### `sources.yaml`

One line per source. See [sources](sources.md) for the fields and how to add one.

### `site.yaml`

| Setting | Meaning |
|---|---|
| `name` | The site's name in the brief |
| `focus`, `ignore` | What counts as a story and what to skip; passed to the AI as-is |
| `groups` | The site's sections. Geopolitical groups are regions (articles belong to the group matching their source's `region`; a new story is filed under the region it is about); Cyber has one group covering several sections. All groups are collected in one run |
| `lists` | Plain headline lists (no AI): `section`, `name`, `days` to look back, `limit` |
| `pages` | The sidebar. Each page has an `id`, a `name`, an `icon` and `show`: the blocks it contains, top to bottom (below) |
| `catch_up_days` | Weekdays whose brief covers several days, for example `monday: 4` (Friday to Monday) |
| `expire_days` | A story with no new reporting for this many days is archived |
| `keep_days` | Daily files older than this are removed from the website (default 365) |

**Blocks** a page can show:

| Block | Shows |
|---|---|
| `bluf` | Bottom line up front |
| `top` | Most reported stories |
| `worldwide` | Stories reported by outlets in the most regions (Geopolitical) |
| `stories` | Every story, by group |
| `group:<id>` | One region: stories by country, other headlines per country, opinion and analysis |
| `regions` | Every region at a glance |
| `countries` | Countries in the news, hotspots first |
| `commentary` | Opinion and analysis pieces |
| `industries` | Industry sections (Cyber) |
| `vulns` | CISA KEV additions and CVEs in the news |
| `iocs` | New indicators of compromise |
| `list:<section>` | One of the headline lists |
| `quality` | Collection and checks: articles collected, events found, reports kept and removed, corroborations |

**Icons**: `dashboard`, `world`, `europe`, `north-america`, `asia`, `mena`, `latin-america`, `africa`,
`brief`, `briefcase`, `plane`, `fingerprint`, `flask`, `broadcast`, `tool`, `rss`, `link`, `eye`, `list`.

### `geo/countries.yaml`

Every country: `id`, `name`, `region`, `global` and `regional` tier (1 to 3), `also` (other words
for it: demonyms, capital, institutions), and `ambiguous: true` when the name alone means something
else. Plus `not_countries` (phrases removed before matching) and `venues` (host cities that count a
quarter). See [geography](geography.md).

### `geo/country_names.yaml`

Country names in other languages, grouped by language. `Name*` matches any ending.

### `geo/entities.yaml`

Names that point to a country without naming it: `places` (cities, states), `institutions`,
`people` (political figures, in office or not) and `companies` (by headquarters; they count half).
Under each heading, `country id: [names]`. See [geography](geography.md#entities).

### `geo/corrections.yaml`

Manual fixes applied on every run. `remove_country` takes everything about one country out of a
story it was wrongly mixed into; `place` puts a story on the region page and countries you choose.
See [stories](stories.md#corrections).

### `geo/toolkit.yaml`

The links on the Toolkit page, in groups. Nothing here is fetched.

### `cyber/industries.yaml`

A shared `concern` word list, then each industry's `topic`, `also_concern`, `exclude` and
`cyber_headline`. See [cyber](cyber.md#industries).

## Shared

| File | What it controls |
|---|---|
| `ai.yaml` | `provider` (`gemini`, `anthropic` or `mock`), `model`, `pause_seconds` between calls, `max_output_tokens` (longest answer; a cut-off answer is retried as two smaller calls); what a run collects: `max_per_source`, `max_per_run`; how groups are sent: `batch_groups` and `batch_articles` per call, `group_articles` shown per group, `max_calls` per site per run |
| `guardrails.yaml` | The checks on every AI sentence: reporting verbs, number/name/wording checks and thresholds, banned analysis words, maximum length |
| `prompts/narratives.md` | The instructions given to the AI |
| `publishers.yaml` | Feeds that belong to one organisation, so they count as one outlet |
| `content_types.yaml` | How opinion, analysis and off-topic sections (sport, entertainment) are recognised: RSS categories, address folders, headline markers, source types; and `story_terms`, words that stop the AI from creating an entertainment or sport story |
| `feeds.yaml` | Which machine feeds to write, how many days they cover, which indicator types to include |

## Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | `narratives.py` | The AI key (or `ANTHROPIC_API_KEY` with `provider: anthropic`) |
| `AI_PROVIDER` | `narratives.py` | Overrides `ai.yaml` for one run; `mock` needs no key |
| `ABUSECH_AUTH_KEY` | `indicators.py` | Optional: enables ThreatFox indicators |
| `SITE_URL` | `machine_feeds.py` | Public address used in feed links; on GitHub it's worked out automatically |
| `SITAWARE_DB` | every script | Use another database file (the tests point it at a throwaway one) |
| `MOCK_MAX_GROUPS` | `llm.py` (mock) | Test mode: pretend answers with more groups than this are cut off, to exercise the split-and-retry |
