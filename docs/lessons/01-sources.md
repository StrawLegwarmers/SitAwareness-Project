# Lesson 1: Sources

**Goal:** a list of feeds the computer can read, stored in a file you can edit, plus a tool
that tells you which feeds work.

**You'll learn:** what RSS really is, how sites advertise their feeds, why config lives in
YAML, and how to add a source.

---

## 1. What an RSS feed actually is

A feed is just a web page written for machines instead of people. Open this in a browser:

    https://feeds.bbci.co.uk/news/world/rss.xml

You'll see XML like this (trimmed):

```xml
<item>
  <title>Democrats win control of Congress</title>
  <link>https://www.bbc.com/news/articles/c123</link>
  <description>Results show the party gained seats in both chambers...</description>
  <pubDate>Wed, 04 Nov 2026 07:12:00 GMT</pubDate>
</item>
```

Every item has the same four things: **title, link, summary, date**. That's all Feedly reads,
and it's all we need. We never scrape full articles. That keeps it fast, cheap, and respectful of
publishers: the site shows a headline and a one-line summary, then links out.

There are two formats (RSS and Atom) and many sites break the rules a little. The Python
library `feedparser` smooths all of that over, so our code just sees `entry.title`,
`entry.link`, and so on.

## 2. Finding a site's feed (discovery)

A typical bookmark list stores **homepages** (`https://www.kyivpost.com/`), not feeds.
Start-page tools quietly find the feed for you. We have to do that ourselves. `pipeline/feeds.py →
discover_feed()` tries three things, cheapest first:

1. **Is the URL already a feed?** Download it and see if `feedparser` finds items.
2. **Is a feed advertised in the page?** Most sites put a tag in their HTML `<head>`:
   ```html
   <link rel="alternate" type="application/rss+xml" href="/feed/">
   ```
   That's the standard. Browsers, Feedly, and our script all look for it.
3. **Guess common paths:** `/feed/`, `/rss/`, `/rss.xml`, etc. WordPress sites (a huge share
   of local news) almost always use `/feed/`.

Running this against a starting list of 190 sites found feeds for 112 automatically. Testing
known feed addresses for big outlets (NYT, DW, TASS...) added about 25 more.

> **Gotcha we hit:** for Middle East Monitor, step 2 found the *comments* feed first
> (`/comments/feed/`). Discovery is a good start, not gospel. Always look at what it found.

## 3. The Google News trick

Some big sources have no public feed (Reuters, AP) or block automated requests (ISW). But
Google News turns **any search into a feed**:

    https://news.google.com/rss/search?q=site:reuters.com+world&hl=en-US&gl=US&ceid=US:en

Change the `q=` part and you have a custom feed. We use this for Reuters, AP, ISW, and the
aviation cyber search (`(airline OR airport OR aviation) (cyberattack OR ransomware OR breach)`).
It's one of the most useful tools in this project, so remember it.

## 4. Why YAML config instead of code

Open `config/geo/sources.yaml`. Each source is one line:

```yaml
- {name: Kyiv Post, feed: "https://www.kyivpost.com/feed/", region: europe, topics: [russia-ukraine], type: local, lang: en}
```

Keeping this out of the Python code is what makes the project **customizable**:

- Adding a source = adding a line. No programming.
- Each site (`geo`, `cyber`) is just a folder in `config/`. A third site later (say
  `config/energy/`) needs no code changes.
- The fields carry meaning the AI will use later:
  - `type: state-media` → the AI will write "TASS reported Moscow claims…" and never state it as fact.
  - `lang: ar` → fine; Claude reads Arabic, French, Polish… and writes the brief in English.
  - `region` / `section` → which page of the site the source feeds.
  - `enabled: false` + `note:` → keep a source on file without fetching it.

`pipeline/config.py → validate()` catches typos (like `region: midle-east`) before they cause
confusing problems later. Making the computer check your config is a habit worth building.

## 5. The health check

`pipeline/check_sources.py` downloads every feed **in parallel** (16 at a time) and prints:

```
  OK    geo   europe    Kyiv Post                            100 items, newest 2026-11-05
  OK    cyber intel     The DFIR Report                       10 items, newest 2026-08-24  <- stale
  FAIL  cyber intel     CISA Advisories                     HTTP 403
131/133 feeds OK, 3 stale, 2 failing.
```

Why parallel? Downloading a feed is mostly waiting for the other server to respond. Waiting
16 at a time makes it about 16x faster than one by one: under a minute instead of ~10.

**About the CISA failure:** CISA's site blocks many cloud servers. It may work from your
computer or from GitHub's servers. If not, we'll switch it to a Google News search feed. Real
pipelines always have a few failing sources. The goal is to *notice*, not to be perfect.

## 6. What made it in

| | Fetched | On file, disabled | Not possible |
|---|---|---|---|
| Geo | 104 feeds (9 global, 1 N. America, 36 Europe, 28 MENA, 30 Africa) | 8 | ~35 sites with no feed; X accounts (need a paid API) |
| Cyber | 29 feeds (10 news, 14 intel, 5 aviation) | 2 | |

OSINT **bookmarks** and **X accounts** aren't news feeds, so they went to
`config/geo/toolkit.yaml`. The site will show them as a **Toolkit** page.

**Coverage gap to know about:** there are no Asia or Latin America sources yet. The global
wires cover the big stories, but you'll want regional sources there. That's your exercise below.

---

## Do it yourself

### A. Put the project on GitHub (10 min)

1. Sign in at github.com. In **Settings → Emails**, tick *Keep my email addresses private*
   so commits show a `noreply` address instead of your real email.
2. **New repository** → name `sitaware` → **Public** (free GitHub Pages needs public;
   your API key will stay secret, see Lesson 6) → tick *Add a README* → Create.
3. On the repo page: **Add file → Upload files**, then drag in the *contents* of the
   `sitaware` folder (`config`, `pipeline`, `docs`, `README.md`, `requirements.txt`,
   `.gitignore`). Commit.
   *(On a Mac, `.gitignore` is hidden in Finder. Press Cmd+Shift+. to show it.)*

### B. Run it in the browser with Codespaces (5 min)

A Codespace is a computer in the cloud with your repo already on it. You don't need to install anything.

1. On the repo page: **Code → Codespaces → Create codespace on main**.
2. In the terminal at the bottom, run:
   ```bash
   pip install -r requirements.txt
   python pipeline/check_sources.py
   ```
3. Watch ~130 feeds get checked. Do the CISA feeds work from GitHub's servers?

### C. Add a source (the real exercise)

Add an Asia source. Pick any outlet you read: SCMP, Nikkei Asia, The Hindu, Yonhap, CNA...

```bash
python pipeline/check_sources.py --discover https://www.scmp.com
```

It prints a ready-to-paste line. Add `asia` as its region, paste it into
`config/geo/sources.yaml` under a new `# ── Asia ──` heading, set `type` and `lang`,
then run `python pipeline/check_sources.py --site geo` and confirm it says **OK**.

Bonus: deliberately type `region: asai` and run the check again. Watch the validator catch it.

### Check your understanding

1. Why do we store `feed` URLs instead of homepages?
2. Reuters has no feed. How do we still get Reuters stories?
3. What will `type: state-media` change about how the AI writes?
4. Why does the checker run 16 downloads at once?

---

**Next, Lesson 2, Fetch & store:** turn "check the feeds" into "save every new article to a
database, once, even if five feeds carry the same story."
