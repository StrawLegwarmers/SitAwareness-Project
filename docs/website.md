# Website

The website (`site/`) is plain HTML, CSS and JavaScript with no framework, no server and no
third-party resources. It reads the JSON that `export.py` writes into `site/data/` and never talks to
an AI. GitHub Pages publishes it; locally, `python -m http.server --directory site 8000` serves it.

## Layout

- **Sidebar** pinned to the left: every Geopolitical page, every Cyber page, your Watchlist, then the
  reference pages (Toolkit, Sources, OpenCTI). Each page shows a count (stories with new reporting, headlines,
  indicators…). At the foot: when the brief was built, sources read and sentences removed by the
  checks. On a phone the sidebar opens from the menu button.
- **Top bar**: the title (a radar that keeps sweeping, and letters that decode once when the site
  opens), the date or range, search, and light/dark mode.
- **Pages** come from `pages:` in each `site.yaml` ([configuration](configuration.md#siteyaml)).

## Stories

Each card shows:

- its **status**: New, Updated (new facts), More coverage (more outlets, no new facts) or Still tracked;
- **flags**: *new for you* (changed since your last visit), *single source*, *state media only*, and
  any watchlist words it mentions;
- **reach** ("6 regions": how many regions' outlets reported it) and the number of outlets in the period;
- its countries, domestic or international;
- the newest checked **reports**, each starting with the date its source published it
  ("On 12 Nov 2026, Reuters reported…"), with links, and the outlets that **also reported** the same
  facts;
- **dates in the reporting**: dates the articles themselves mention, counted by outlet;
- under **Sources and earlier reporting**, every original headline and earlier report;
- first seen, articles in total, the wire and state-media mix, and **Copy with sources**: the
  title, reports and headlines as plain text, every sentence with its link, ready to paste.

Opinion and analysis pieces are listed separately with their outlet's label.

**Cards / List** at the top of each page switches to a compact list (one line per story, details on
demand). The choice is remembered.

**Collection and checks** (Overview, Cyber brief) shows the run's numbers: articles collected, events
reported by two or more outlets, groups checked by the AI, stories with new reports, reports kept and
removed, corroborations, and groups waiting for the next run.

## Yours: new since your last visit, and the watchlist

Both live in your browser only (local storage): nothing is sent anywhere, and another browser or
device starts empty.

- **New since your last visit**: opening the latest brief remembers which stories you've seen. Next
  time, stories with a new report are marked *new for you*, and the page says how many.
- **Watchlist** (sidebar, Yours): add words you follow, such as a country, a person, a company or a
  place. The page collects every story and headline that mentions them, on both sites, and cards
  everywhere carry a marker. A word matches at the start of a word: "Iran" finds "Iranian" but not
  "Tirana".

## Dates and ranges

The date button opens a calendar; days with a brief can be picked.

- **One day**: that day's brief exactly as it was published.
- **Several days**: pick the first and last day (up to 14). The browser downloads those days' files and
  merges them into one view with the same pages: every story active in the period with all its
  reports, outlet counts over the whole period, combined headline lists, vulnerabilities, indicators
  and country headlines. A banner names the days combined.
- **Shortcuts**: Latest, last 3, 5, 7 or 14 days.
- **‹ ›** move one day, or shift a range by its own length.

The address records the page and period, for example `#/geo/2026-11-07..2026-11-11/europe` or
`#/geo/europe/c-poland` (scrolled to Poland), so views can be bookmarked and shared. The 14-day limit
(`max_range_days` in `export.py`) keeps downloads reasonable: each geopolitical day is about half a
megabyte.

## Search and folding

- **Search** covers everything in the current view: stories, reports, headlines, industry matches,
  opinion pieces and per-country headlines. Matches are highlighted.
- **Search the last 30 days** (below the results) searches the stories of the last 30 briefs, from a
  small index file (`site/data/<site>/search-index.json`) downloaded only when you ask. Each result
  links to that day's page.
- **Every section heading folds** what's under it; click again to open. Your browser remembers what
  you folded (stored only in your browser).

## Security

The site displays text written by thousands of outside publishers, so it treats all of it as
untrusted:

- **Everything is escaped** before display, so a headline can never become HTML.
- **Only ordinary web links** (`http`, `https`) become clickable; anything else becomes a harmless `#`.
- **Content Security Policy**: the browser may only load scripts, styles and data from the site
  itself, so even injected markup couldn't load or run outside code.
- **No referrer** is sent to news sites when you follow a link.
- **Indicators of compromise** are always shown defanged and never as links.

Tested with deliberately malicious headlines, names and addresses in every data file: nothing runs.

## Accessibility

- **Keyboard**: a "Skip to the brief" link comes first; every section heading holds a button that
  folds the section (Enter or Space), and says whether it's open; after moving to another page the
  focus goes to the top of the new page.
- **Screen readers**: headings stay headings; the browser tab's title names the page, site and
  date; "Copied" is announced; loading and error messages are announced too.
- **Colour**: links inside sentences are underlined; text and buttons meet WCAG AA contrast in both
  themes (checked with axe-core on every page).
- **Errors**: a file that fails to download shows a message and a "Try again" button instead of a
  blank page.

## Icons and appearance

Icons are inline SVG, so nothing is loaded from elsewhere. Most come from
[Tabler Icons](https://tabler.io/icons) (MIT licence); the continent outlines are drawn for this
project. Colours are variables at the top of `site/assets/style.css`, with a dark theme that follows
the system setting or the theme button. Animations stop for anyone whose system is set to reduce
motion.
