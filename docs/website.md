# Website

The website (`site/`) is plain HTML, CSS and JavaScript with no framework, no server and no
third-party resources. It reads the JSON that `export.py` writes into `site/data/` and never talks to
an AI. GitHub Pages publishes it; locally, `python -m http.server --directory site 8000` serves it.

## Layout

- **Sidebar** pinned to the left: every Geopolitical page, every Cyber page, then the reference pages
  (Toolkit, Sources, OpenCTI). Each page shows a count (stories with new reporting, headlines,
  indicators…). At the foot: when the brief was built, sources read and sentences removed by the
  checks. On a phone the sidebar opens from the menu button.
- **Top bar**: the title (a radar that keeps sweeping, and letters that decode once when the site
  opens), the date or range, search, and light/dark mode.
- **Pages** come from `pages:` in each `site.yaml` ([configuration](configuration.md#siteyaml)).

## Stories

Each card shows its status (New, Updated, Still tracked), flags (single source, state media only),
the number of outlets in the period, its countries with domestic or international, the newest checked
reports with links, and under **Sources and earlier reporting** every original headline and earlier
report. Opinion and analysis pieces are listed separately with their outlet's label.

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

## Icons and appearance

Icons are inline SVG, so nothing is loaded from elsewhere. Most come from
[Tabler Icons](https://tabler.io/icons) (MIT licence); the continent outlines are drawn for this
project. Colours are variables at the top of `site/assets/style.css`, with a dark theme that follows
the system setting or the theme button. Animations stop for anyone whose system is set to reduce
motion.
