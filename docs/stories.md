# Stories and guardrails

`pipeline/narratives.py` turns the day's articles into **stories** (running events) and writes short
**reports**: one sentence each, saying what one outlet reported, with its source. The AI's job is
deliberately narrow; everything else is code, and the code checks the AI's work.

```bash
python pipeline/narratives.py                            # every site, every group
python pipeline/narratives.py --site geo --group europe  # one group
python pipeline/narratives.py --site geo --dry-run       # write the prompts to data/prompts/, no AI call
python pipeline/narratives.py --site geo --show          # print the stories being tracked
python pipeline/narratives.py --site geo --audit         # what the checks removed, and why
AI_PROVIDER=mock python pipeline/narratives.py           # test mode: no key, deliberately bad sentences
```

## One run

For each group in `site.yaml` (one region, or the Cyber group):

1. **Select** the news articles that arrived since the group's last run (opinion and analysis are
   never sent). At most `max_per_source` per source; if the total exceeds `max_per_call`, every
   source is trimmed evenly rather than cutting off the oldest hours.
2. **Prompt** the AI with (A) every story already tracked on the site and (B) the numbered new
   articles. The instructions are in `config/prompts/narratives.md`: continue an existing story
   before creating one; a new story needs at least two articles; each report cites article numbers
   such as `[12]`; report only what was reported, with no assessment; attribute state media.
3. **Check** every report and title (below), insert the real links, drop duplicates, and save.

Groups run in order, and later groups can continue stories created by earlier ones. Global runs
last, so global outlets add to regional stories instead of duplicating them. A short pause between
calls keeps within free-tier rate limits. If a call fails, that group's articles are retried on the
next run.

Afterwards each story gets its status from dates (**new** today, **updated** today, or **still
tracked**), so running twice in one day gives the same result as running once. A story with no new
reporting for `expire_days` is archived.

## The checks

`pipeline/guardrails.py`, configured in `config/guardrails.yaml`. A sentence must pass all of them:

| # | Check | Rejects |
|---|---|---|
| 1 | Cites a real article by number | Sentences with no source, or a number that doesn't exist |
| 2 | Attributed with a reporting verb ("reported", "said", "according to"…) | Claims stated as fact |
| 3 | Every number appears in the cited articles (digits and number words) | Changed or invented figures |
| 4 | At least 70% of capitalised names appear in the cited articles (English sources) | Invented people, places, organisations |
| 5 | At least 65% of the meaningful words come from the cited articles | The AI's own conclusions and paraphrase drift |
| 6 | No analysis words ("likely", "signals", "escalation", "unprecedented"…) unless the source used them | Assessment dressed as reporting |
| 7 | At most 45 words | Run-on summaries |

The AI writes `[12]`; code replaces it with a link to article 12's outlet. **The AI never writes a
web address.** When the AI names an outlet instead of a number, code adds the number only if that
outlet really published one of the articles it pointed to.

Story **titles** are checked the same way; a title that fails is replaced by a real headline.

Every removed sentence is logged in `state/<site>/audit.json` with the reason, kept 7 days, and
counted at the foot of the website. Run `python pipeline/guardrails.py` to see the checks applied to
examples.

## Duplicates

| Situation | What happens |
|---|---|
| The AI proposes a "new" story that matches one already tracked | Merged into the existing one, if both have at least 6 meaningful words, share at least 3, overlap by at least 50%, and have at least one country in common |
| A report repeats one already in the story (80% the same, or the same articles on the same day) | Skipped |
| An opinion or analysis piece sits in a story | Removed from the story; a report resting only on such pieces is removed and logged |

The country condition matters for stories whose headlines are mostly in other languages: described
by only a few English words, two unrelated stories can look 50% similar by accident.

## Corrections

When grouping goes wrong anyway, fix it in `config/geo/corrections.yaml` rather than in the state
files (which the daily run rewrites):

```yaml
remove_country:
  - {story: "Exact story title as shown on the website", country: spain}
```

On every run, articles and reports that mention that country and none of the countries in the
story's own title are taken out of the story and logged in the audit. They then appear under the
country on its region page, and a later run can start a proper story for them. An old rule does
nothing once the story is clean or archived.

## Ranking and the brief

- **Outlets** are counted per publisher (`config/publishers.yaml`), over the period the brief covers.
- **Most reported** and the **BLUF** (bottom line up front) are the five stories with the most
  outlets. Each BLUF line is the newest checked report for that story, or a real headline if none
  passed the checks. No new text is written for the BLUF.
- **Flags**: *single source* (one outlet) and *state media only* (every source is government-run).
- **Catch-up days**: `catch_up_days: {monday: 4}` makes Monday's brief cover Friday to Monday.
  Nothing is re-run; reports and articles carry the date they arrived, so the brief counts over a
  longer window.

## AI providers

`config/ai.yaml` selects the provider: `gemini` (Google's API, which has a free tier), `anthropic`, or
`mock` (no AI, for testing). Output is forced into a fixed JSON shape. The key is read from an
environment variable and never written anywhere.
