# Operations

The tool runs on GitHub: a scheduled workflow builds the brief every 3 hours and GitHub Pages
publishes it. Both are free for public repositories.

## Setting up a copy

1. **Fork or copy the repository** to your own GitHub account.
2. **Add the AI key** as an encrypted secret: *Settings → Secrets and variables → Actions → New
   repository secret*, name `GEMINI_API_KEY`. Create the key in Google AI Studio; restrict it to the
   Generative Language API. Never paste a key into a file.
3. **Optional**: add `ABUSECH_AUTH_KEY` (a free key from abuse.ch) to enable ThreatFox indicators.
   Add `SEC_CONTACT_EMAIL` (a contact address the SEC and BLS ask automated requests to carry) to
   enable SEC filings and the BLS calendar on the Markets site; see [markets](markets.md#the-contact-email-sec_contact_email).
4. **Enable Pages**: *Settings → Pages → Source: GitHub Actions*.
5. **Run it**: *Actions → Daily brief → Run workflow*. The site appears at
   `https://<account>.github.io/<repository>/`.
6. **Optional**: create an issue label named `source` for source requests.

## The workflow (every 3 hours)

`.github/workflows/daily.yml`:

| When | What |
|---|---|
| 00:37, 03:37, 06:37 … 21:37 UTC | A run every 3 hours (off the hour on purpose: GitHub delays or drops scheduled runs at busy times such as the top of the hour). A dropped run is caught up by the next one |
| Any time | *Run workflow* on the Actions tab |

Steps: restore the last run's database and website data from the Actions cache → fetch feeds →
turn off feeds that keep failing (below) → collect vulnerabilities and indicators (allowed to fail
without stopping the run) → market data: rates, calendar, SEC filings (also allowed to fail) →
group stories → write the website's data and feeds → save the database and website data to the
cache → commit as `github-actions[bot]` → publish `site/` to Pages. Two runs never overlap.

### Several runs a day

- **Each run looks at the last 24 hours**, not just at what arrived since the last run, so two
  outlets reporting the same event hours apart still make a story. Articles already in a story are
  left out, and the AI is only sent groups with something it hasn't checked yet (see
  [stories](stories.md#one-run)). A quiet run sends nothing to the AI at all.
- **What gets committed.** `state/` (the stories' memory, a few tens of KB per run) every run. The
  website's data once a day: a finished day's files at the next day's first run, and today's at
  the 21:37 run as a safety copy. Between commits, the latest files travel in the Actions cache
  and are published to Pages each run. Committing the website data every run would grow the
  repository by about 1 GB a year; this way it is about 0.2 GB.
- **The website** shows the day's brief so far, with the time it was last updated.

### AI limits

`limits` in `config/ai.yaml` holds your project's limits as Google AI Studio shows them (for
Gemini 3.5 Flash-Lite on the free tier: 15 requests a minute, 250,000 input tokens a minute, 500
requests a day). The pipeline uses at most 80% of each (`share`): before every request it waits
if the last minute is full, and once the day's budget is used it stops calling, so the remaining
groups wait for the next run after midnight Pacific time, when Google resets the count. Every
attempt counts, retries included, as on Google's dashboard. The day's count is in
`state/ai-usage.json`. A typical run makes 1 to 10 calls; a busy morning run, up to about 20.

### Feeds that keep failing

A feed that has failed on every run for 7 days (and at least 5 runs in a row) is turned off:
`enabled: false` and a dated note ("Auto-disabled 2026-11-20: failing since 2026-11-13 (HTTP 403)")
are written into its line in `sources.yaml`, and it shows as Disabled on the Sources page with that
note. Re-enable it with a "Change a source" issue once it works. If more than a fifth of the feeds
fail at once, nothing is turned off: that's a network problem, not the feeds. To preview:
`python pipeline/manage_sources.py auto-disable --dry-run`.

To run a fresh build after changing code, use **Run workflow**. **Re-run all jobs** on an old run
re-uses that run's version of the code.

## The tests workflow

`.github/workflows/tests.yml` runs the automated tests (`tests/`) on every push and pull request:
about 110 checks of feed parsing, grouping accuracy on a labelled day, the guardrails, grouping, placement, dates, the AI-answer checks,
the machine feeds, the source-request validation, and security rules (no keys or personal email
addresses in the repository, no untrusted text pasted into workflow commands, least-privilege
permissions, the website's security policy). It needs no key, no network and no AI (the mock is
used), and also checks that every configuration file is valid. Run them locally with:

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python pipeline/check_sources.py --validate-only     # config files only, no downloads
```

A red cross on the Actions tab means a change broke something; the daily brief is a separate
workflow and keeps running.

## The maintenance workflow

`.github/workflows/maintenance.yml` runs only when you start it (Actions → Maintenance → Run
workflow). Unticked, it lists the stories that mix unrelated events and the new wider-story names it
would use; with *apply* ticked, it splits those stories, renames them and commits `state/`. See
[stories](stories.md#maintenance). It uses the AI key: the AI double-checks code's suspicions and
proposes names, and code checks every name.

## Pinned actions and Dependabot

Every action in the workflows is pinned to an exact commit, with its version in a comment
(`actions/checkout@3d3c42e…  # v7.0.1`): a version tag can be moved to other code, a commit
can't. `.github/dependabot.yml` asks GitHub's Dependabot to check weekly for newer versions of the
actions and of the Python libraries; it opens a pull request, the tests run on it, and you merge it
if they pass. The tests fail if an action isn't pinned.

## Workflow permissions

Each workflow starts with no permissions (`permissions: {}`) and each job gets only what it needs:
the daily `check` job can only read; `build` can commit (`contents: write`) and read the Pages
settings; only `deploy` can publish and request the identity token Pages uses. The source-request
job can commit and reply on issues; maintenance can commit; the tests can only read.

## The source-request workflow

`.github/workflows/manage-sources.yml` reacts to issues opened with the "Add a source" or "Change a
source" forms (`.github/ISSUE_TEMPLATE/`), only for the owner and collaborators. See
[sources](sources.md#adding-or-changing-sources-from-the-browser).

## Limits

| Service | What to watch |
|---|---|
| AI (Gemini free tier) | Requests per minute and per day, and tokens per minute, per Google Cloud project; daily quotas reset at midnight Pacific time. Kept under 80% by the pipeline (see AI limits). One run makes up to `max_calls` calls per site, paused at least 15 seconds apart |
| GitHub Actions | Free for public repositories. A run takes about 6 minutes; 8 a day |
| Repository size | GitHub recommends under 1 GB. About 0.2 GB a year with website data committed once a day (see Several runs a day) |
| GitHub Pages | Published sites up to about 1 GB. Daily files are kept for 12 months (`keep_days`), which stays well under it |
| Feeds | Some outlets block or rate-limit automated readers; see the Sources page |

## Retention

- **Website files**: daily briefs, headline files and indicator CSVs older than `keep_days` (365) are
  removed by each run. Git keeps every earlier version in its history.
- **Database**: articles older than 30 days are deleted.
- **Audit log**: removed sentences are kept 7 days.
- **Stories**: archived after `expire_days` without new reporting; the last 100 are listed in the state.

## Working locally or in a Codespace

```bash
git pull                                          # always start up to date
pip install -r requirements.txt
python pipeline/fetch.py && python pipeline/indicators.py
AI_PROVIDER=mock python pipeline/narratives.py    # or set GEMINI_API_KEY for real output
python pipeline/export.py
python -m http.server --directory site 8000
git restore state                                 # drop local test results before pulling again
```

A Codespace reads `GEMINI_API_KEY` from *Settings → Codespaces → Secrets*, separate from the Actions
secret.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| The workflow fails at "Group stories" with "GEMINI_API_KEY is not set" | The secret is missing or misnamed |
| Many reports removed in the audit | Normal on busy days; read `python pipeline/narratives.py --audit` to see why |
| An AI call failed with a rate-limit error | The free-tier quota was reached; its articles are retried on the next run. Lower `max_calls` in `ai.yaml` if it keeps happening |
| "An AI call failed" on the Overview | The reason is shown there ("cut off at the output limit", "HTTP 429"...). Cut-off answers are already retried as two smaller calls; if it keeps happening, lower `batch_groups` in `ai.yaml` |
| A story is on the wrong region page | Run `python pipeline/countries.py --stories` to see which rule placed it; add the missing name to `entities.yaml`, or fix that story with `place:` in `corrections.yaml` |
| Unrelated articles in one story, or one event split in two | Run `python pipeline/cluster.py --site geo` to see the code's groups; use `remove_country` in `corrections.yaml` for a mixed story |
| A source shows Failing | Check its error on the Sources page; disable it or replace its address |
| `git pull` refuses: "local changes would be overwritten" | Test output in `state/`: run `git restore state`, then pull |
| A YAML error stops the run | The message names the file and line; usually indentation or a missing quote |
| The site shows yesterday | The run hasn't finished, or failed; check the Actions tab |

## Security checklist

- Keys only in GitHub secrets; nothing secret in the repository or the website.
- Keep your email private (*Settings → Emails*) and commit with the no-reply address.
- Enable secret scanning and push protection (*Settings → Code security*).
- Turn on two-factor authentication.
- Restrict the AI key to the API it needs.
- Only add collaborators you trust: they can trigger the source workflow and edit files directly.
- Uploading files through the GitHub website stamps the commit with your computer's time zone
  (for example `+0100`). Commit from a terminal with `TZ=UTC git commit ...` if that matters to you.
- Rewriting history doesn't remove old commits from GitHub's caches: a commit that was ever pushed
  stays reachable by its address until GitHub Support purges it (*Remove data from a repository*
  in GitHub's documentation), or the repository is deleted and recreated.
- The IOC files under `site/feeds/` are published with real (refanged) values on purpose, for
  tools like OpenCTI. Security scanners can flag a site that lists live malicious addresses; if
  that happens, turn off `iocs_csv` and `stix` in `config/feeds.yaml`, or host the feeds privately.
