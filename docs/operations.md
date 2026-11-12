# Operations

The tool runs on GitHub: a scheduled workflow builds the brief each morning and GitHub Pages
publishes it. Both are free for public repositories.

## Setting up a copy

1. **Fork or copy the repository** to your own GitHub account.
2. **Add the AI key** as an encrypted secret: *Settings → Secrets and variables → Actions → New
   repository secret*, name `GEMINI_API_KEY`. Create the key in Google AI Studio; restrict it to the
   Generative Language API. Never paste a key into a file.
3. **Optional**: add `ABUSECH_AUTH_KEY` (a free key from abuse.ch) to enable ThreatFox indicators.
4. **Enable Pages**: *Settings → Pages → Source: GitHub Actions*.
5. **Run it**: *Actions → Daily brief → Run workflow*. The site appears at
   `https://<account>.github.io/<repository>/`.
6. **Optional**: create an issue label named `source` for source requests.

## The daily workflow

`.github/workflows/daily.yml`:

| When | What |
|---|---|
| 07:37 UK time | Main run (off the hour on purpose: GitHub delays or drops scheduled runs at busy times such as the top of the hour) |
| 09:23 UK time | Backup run: builds the brief only if the main run didn't; otherwise stops within seconds |
| Any time | *Run workflow* on the Actions tab always builds |

Steps: restore yesterday's database from the Actions cache → fetch feeds → collect vulnerabilities and
indicators (allowed to fail without stopping the run) → group stories → write the website's data and
feeds → save the database → commit `state/` and `site/data/` as `github-actions[bot]` → publish
`site/` to Pages. Two runs never overlap.

To run a fresh build after changing code, use **Run workflow**. **Re-run all jobs** on an old run
re-uses that run's version of the code.

## The source-request workflow

`.github/workflows/manage-sources.yml` reacts to issues opened with the "Add a source" or "Change a
source" forms (`.github/ISSUE_TEMPLATE/`), only for the owner and collaborators. See
[sources](sources.md#adding-or-changing-sources-from-the-browser).

## Limits

| Service | What to watch |
|---|---|
| AI (Gemini free tier) | Requests per minute and per day, and tokens per minute, per Google Cloud project; daily quotas reset at midnight Pacific time. One run makes up to `max_calls` calls per site (8 by default; usually fewer for Cyber), paused 15 seconds apart. Check current quotas in Google AI Studio |
| GitHub Actions | Free for public repositories. A run takes about 10 to 15 minutes |
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
