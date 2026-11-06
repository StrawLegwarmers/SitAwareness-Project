# Lesson 2: Fetch & store

**Goal:** every run downloads all feeds and saves each *new* article to a database exactly
once, even when the same story shows up in several feeds or with a different link.

**You'll learn:** what a database gives you over files, the two kinds of duplicates and how
to catch them, cleaning messy feed data, polite fetching, and your first SQL.

**New files:** `pipeline/normalize.py`, `pipeline/store.py`, `pipeline/fetch.py`,
`pipeline/stats.py`, `pipeline/sql.py` (and a small change to `pipeline/feeds.py`).

---

## 1. Why a database?

Lesson 1 *looked* at feeds. Now we need to **remember**:

- Which articles have we already seen? (So we only process new ones.)
- What did each region look like over the last week? (Lesson 3 compares today with yesterday.)
- Which feeds have been failing for three days in a row?

You could keep all that in JSON files, but you'd end up rewriting a database by hand. We use
**SQLite**: a complete database in a single file (`data/sitaware.db`). It's built into Python
and needs no server. You talk to it in SQL, the language nearly every database uses.

Open `pipeline/store.py` and read the `SCHEMA` at the top. Three tables:

| Table | One row per… | Used for |
|---|---|---|
| `articles` | article | everything downstream |
| `feed_state` | feed | remembering ETags (section 5) and failure streaks |
| `fetch_log` | feed per run | health history |

## 2. Cleaning: making every feed look the same

`pipeline/normalize.py` turns each raw feed entry into the same clean record:

- **HTML stripped from summaries.** Many feeds embed `<p>`, `<img>` and `&amp;` in the summary.
- **Summaries cut to 500 characters.** That's plenty for the AI, and we're not republishing articles.
- **Dates fixed.** No date? Use the moment we first saw it (Crisis Group's feed has none).
  A date in the future? That's a timezone bug, so clamp it to now.
- **Google News unwrapped.** A Google News item says the source is "Google News", but the real
  publisher is inside it. We store both: `source` = the feed it came from, `outlet` = who
  actually wrote it. That's how the aviation search feed shows "FlightGlobal", "The Star" and so on.

## 3. Duplicates, type 1: the same article in different clothing

Look at this real link from Al Jazeera's feed:

    https://www.aljazeera.com/news/2026/11/6/courts-grant-...-pardon?traffic_source=rss

`?traffic_source=rss` is a tracking tag. DW adds `?maca=en-rss-...`, and newsletters add
`?utm_source=...`. Same article, different URL. `canonical_url()` strips those, forces
`https`, lowercases the host and drops trailing slashes. Then:

    id = hash(site + canonical_url)

The `id` is the database's **primary key**, so inserting the same id twice is impossible.
That one rule makes the pipeline **idempotent**: you can run it 10 times and get the same
result as running it once. That's the property that makes it safe to re-run after a crash.

## 4. Duplicates, type 2: the same story at a different address

An AP story gets republished by five newspapers, each at its own URL. Or a Google News feed
gives the same article a fresh link tomorrow. The URLs differ, but the **headline** doesn't.

`title_key()` makes a headline fingerprint (lowercase letters and digits only), and
`is_title_dupe()` skips an article if the same site already has that fingerprint from the
last 3 days.

**Trade-off:** short generic headlines like "Live updates" or "Morning briefing" would collide
by accident, so fingerprints under 25 characters are never treated as duplicates.
Every dedupe rule is a judgment call like this: too strict and you lose stories, too loose and
you get repeats.

> **Note:** we deliberately do *not* merge different outlets reporting the same *event*
> ("Iran says tankers hit mines" from IRNA *and* from France 24). That's the signal Lesson 3
> needs: how many outlets, from which sides, are covering a story.

## 5. Being polite: conditional requests

On the second run, most servers answered **304 Not Modified** with an empty body. How:

1. The first time we download a feed, the server sends an `ETag` (a version fingerprint) and/or a
   `Last-Modified` date. We save them in `feed_state`.
2. Next time we send them back: "only send this if it changed".
3. If nothing changed, the server replies 304 and we skip the feed.

Less bandwidth for them, faster runs for us. It also makes it less likely that a site blocks you.

## 6. Threads and the database

Downloads still run 16 at a time, but **only downloads**. All database writes happen
afterwards, one feed at a time, in the main thread. A SQLite connection can't safely be
shared between threads, and the writes take milliseconds anyway. A useful rule: run the slow
waiting (network) in parallel and keep shared state (the database) in one place.

Nothing is saved until `conn.commit()` at the end. If the run crashes halfway, the database
stays as it was before the run. That's a **transaction**.

## 7. The 3-day window and the 30-day memory

- **`WINDOW_DAYS = 3`** in `fetch.py`: ignore items older than 3 days. Atlantic Council's
  feeds hold 100 items going back months, and we don't want those on the first run.
- **`KEEP_DAYS = 30`** in `store.py`: delete articles older than 30 days at the end of each run,
  so the database stays small (roughly 1 KB per article).

## 8. What a real day looks like

From a test run (yours will differ a bit):

```
Fetching 134 feeds...
  FAIL  geo   AMAP (Mali): ConnectTimeout
  FAIL  geo   Mareeg: HTTP 202
Feeds:    132 downloaded, 0 unchanged (304), 2 failed
Articles: 3573 new (cyber 208, geo 3365), 78 already stored, 12 duplicate stories, 1720 older than 3 days
```
Run it again immediately:
```
Feeds:    82 downloaded, 50 unchanged (304), 2 failed
Articles: 5 new (cyber 0, geo 5), 2641 already stored, 6 duplicate stories, 1307 older than 3 days
```

Over 24 hours that's about **2,400 geo articles** (half of them Europe, with La Razón, BILD
and TASS the busiest) and about **100 cyber articles**, in 15+ languages. No human reads 2,400
headlines a day, and sending all of them to an AI every day would be slow and costly.
**That's the problem Lesson 3 solves.**

## 9. Where does the database live?

In your Codespace it's just a file: `data/sitaware.db`. **We don't commit it to GitHub.**
Git keeps every version of every file, so a 30 MB database that changes daily would bloat the
repo by about 30 MB a day. In Lesson 6 the daily robot keeps it in GitHub's *Actions cache*
instead. The permanent, public record will be the small daily JSON files the site reads.

So the database is **working memory**, and the JSON files are the **published record**.
Keeping those two separate is a common pattern.

---

## Do it yourself

### A. Get the new files into your repo (5 min)

1. Unzip `lesson-02.zip`. It contains a `pipeline` folder and a `docs` folder.
2. On your repo page on GitHub: **Add file → Upload files** → drag in **both folders** →
   **Commit changes**. Files with the same name are replaced, and your other files stay as they are.
3. Reopen your Codespace (Code → Codespaces → click its name) and pull the changes down:
   ```bash
   git pull
   ```
   `pull` is the opposite of `push`: it brings GitHub's latest version into the Codespace.

### B. Keep the database out of Git

```bash
echo "data/" >> .gitignore
```
`>>` *adds* a line to the end of the file (a single `>` would replace the whole file).

### C. Fetch, twice

```bash
python pipeline/fetch.py
python pipeline/fetch.py
```
Compare the two summaries. Why did the second run find almost nothing new? How many feeds
answered 304?

### D. Look inside

```bash
python pipeline/stats.py
python pipeline/stats.py --site cyber --latest 20
python pipeline/stats.py --search Ukraine
```

### E. Your first SQL

`sql.py` runs any query against the database. It opens the database read-only, so you can't
break anything.

```bash
python pipeline/sql.py "SELECT lang, COUNT(*) AS n FROM articles GROUP BY lang ORDER BY n DESC"
```
Read it as: *from `articles`, group rows by language, count each group, and show the biggest first.*

Now try writing these yourself (answers at the bottom):
1. How many articles came from `state-media` sources?
2. Which 5 outlets in the aviation Google News feed published most?
3. All headlines tagged with the `russia-ukraine` topic, newest first.

### F. Save your work

```bash
git status
```
Check that `data/` is **not** in the list (that means `.gitignore` worked), then:
```bash
git add .
git commit -m "Lesson 2: fetch and store"
git push
```

### What to send back

Paste the output of:
```bash
python pipeline/stats.py | head -30
```
The **"Feeds currently failing"** part shows which 6 feeds fail from GitHub's servers.

### Check your understanding

1. What makes running `fetch.py` twice safe?
2. Why do we strip `?traffic_source=rss` before hashing a URL?
3. Why aren't headlines under 25 characters checked for duplicates?
4. Why isn't `data/sitaware.db` committed to GitHub?

---

**Next, Lesson 3, Narratives:** Claude reads the day's articles region by region, groups them
into running stories, and compares them with yesterday's. You'll need your Claude API key.

<details><summary>SQL answers</summary>

```sql
SELECT COUNT(*) FROM articles WHERE type = 'state-media'
SELECT outlet, COUNT(*) AS n FROM articles WHERE source LIKE 'Google News%' GROUP BY outlet ORDER BY n DESC LIMIT 5
SELECT published, outlet, title FROM articles WHERE topics LIKE '%russia-ukraine%' ORDER BY published DESC
```
</details>
