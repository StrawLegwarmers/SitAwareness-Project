# SitAwareness Project

An open-source "Feedly on steroids": it reads ~130 RSS feeds every day, uses Claude to group the
articles into running **narratives**, tracks how those narratives change from day to day, and
publishes two sites:

- **/geo**: Geopolitical daily (Global, North America, Europe, MENA, Africa, plus conflict topics)
- **/cyber**: Cyber daily (Global Intelligence, New IOCs, Cyber News, Narratives, Aviation industry)

It's built as a learning project, one layer at a time. Each lesson lives in `docs/lessons/`.

## How it works

```
 config/*.yaml          pipeline/ (Python, runs daily on GitHub Actions)              site/ (GitHub Pages)
┌──────────────┐   ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌──────────┐   ┌──────────────────┐
│ sources.yaml │──▶│  fetch   │──▶│  store   │──▶│ narratives │──▶│  export  │──▶│ /geo/   /cyber/  │
│ (what to     │   │ RSS → py │   │ SQLite,  │   │ Claude:    │   │ daily    │   │ static HTML + JS │
│  read)       │   │ objects  │   │ dedupe   │   │ group,     │   │ JSON     │   │ reads the JSON   │
└──────────────┘   └──────────┘   └──────────┘   │ compare w/ │   │ files    │   └──────────────────┘
                                                 │ yesterday  │   └──────────┘
                                                 └────────────┘
```

The one idea to hold on to: **each layer only talks to the next one through files.**
Config → YAML. Pipeline → JSON. Website → reads JSON. That's what lets you change one part
(say, swap the website design) without touching the others.

## Folder map

| Path | What's in it | Lesson |
|---|---|---|
| `config/geo/sources.yaml` | Geopolitical feeds | 1 |
| `config/geo/toolkit.yaml` | OSINT bookmarks shown as a reference page | 1 |
| `config/cyber/sources.yaml` | Cyber news, threat research and aviation feeds | 1 |
| `pipeline/feeds.py` | Check a feed, discover a website's feed | 1 |
| `pipeline/config.py` | Load and validate the YAML | 1 |
| `pipeline/check_sources.py` | Health check for every source | 1 |
| `pipeline/fetch.py`, `store.py` | Daily fetch into a database | 2 |
| `pipeline/narratives.py` | Claude groups articles into narratives | 3 |
| `pipeline/export.py` | Writes the daily JSON the site reads | 4 |
| `site/` | The two websites | 5 |
| `.github/workflows/` | The daily schedule | 6 |

## Roadmap

1. **Sources**: what RSS is, finding feeds, a config you can edit 
2. **Fetch & store**: download everything daily, remove duplicates, keep history
3. **Narratives**: Claude groups articles and compares them with yesterday
4. **The daily brief**: headline, overview, watch list, and the JSON "contract"
5. **The website**: one site, `/geo` and `/cyber`
6. **Automation**: GitHub Actions runs it every morning and publishes to GitHub Pages
7. **Cyber extras**: IOC feeds (abuse.ch, CISA KEV) and the aviation industry page
8. **Adding sources from the browser** and other customization

## Quick start

```bash
pip install -r requirements.txt
python pipeline/check_sources.py            # test every feed
python pipeline/check_sources.py --discover https://www.scmp.com   # find a new site's feed
```
