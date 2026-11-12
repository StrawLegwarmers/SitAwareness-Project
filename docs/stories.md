# Stories and guardrails

`pipeline/narratives.py` turns the day's articles into **stories** (running events) and writes short
**reports**: one sentence each, saying what one outlet reported, with its source. Code does the
grouping and the bookkeeping; the AI's job is deliberately narrow (check each group, restate what
was reported), and the code checks the AI's work.

```bash
python pipeline/narratives.py                            # every site
python pipeline/narratives.py --site geo --group europe  # only articles from one group's sources
python pipeline/narratives.py --site geo --dry-run       # write the prompts to data/prompts/, no AI call
python pipeline/narratives.py --site geo --show          # print the stories being tracked
python pipeline/narratives.py --site geo --audit         # what the checks removed, and why
python pipeline/cluster.py --site geo                    # how the last 24 hours group into events (no AI)
AI_PROVIDER=mock python pipeline/narratives.py           # test mode: no key, deliberately bad sentences
```

## One run

1. **Select** the news articles that arrived since the last run, from every group's sources at
   once (opinion, analysis and off-topic sections are never sent). At most `max_per_source` per
   source; if the total exceeds `max_per_run`, every source is trimmed evenly rather than cutting
   off the oldest hours.
2. **Group the headlines in code** (`pipeline/cluster.py`). Two headlines are about the same event
   when they share at least three *rare* words worth enough together, at least one of them a name
   (a word capitalised inside the headline), and their countries don't clash. Rarity is measured on
   the run's own articles, so "Abu Dhabi" or "Hegseth" count and "says" or "government" don't.
   Words that are common in their own language never count (each language's little words are
   listed in `cluster.py`, and in a language with 150+ headlines, any word in 12% of them).
   Each group is also compared with the stories already tracked: when a third of its headlines
   match a story's headlines, sharing a *distinctive* name (not a country, and not a name in more
   than 2% of the day's headlines, like "Trump" or "Gaza"), code suggests "continues: <story>".
3. **Choose what goes to the AI**: every group reported by two or more outlets, and every group
   (even one article) that continues a tracked story. Biggest first, about 40 groups per call
   (`batch_groups`), showing at most 10 articles per group (`group_articles`), up to `max_calls`
   calls. Groups that don't fit wait for the next run.
4. **Prompt** the AI with (A) the tracked stories its groups may continue and (B) the numbered
   groups. The instructions are in `config/prompts/narratives.md`: check each group and leave out
   articles that don't belong; continue a tracked story before creating one; return a story for
   every group that fits the site's focus; a new story needs at least two articles; report only
   new facts; each report cites article numbers such as `[12]`; no assessment; attribute state media.
5. **Check** the AI's answer (below): every report and title, every story it continues, every
   story it creates. Insert the real links, record corroboration, and save. A group's articles
   that the AI didn't see are added to the same story by code, if each one passes the grouping
   test against an article the AI placed there. They are listed as coverage, never used for a report.
6. **Merge** stories that turn out to be the same event (the AI started one in two different calls):
   when half the headlines of one match the other's, in the same countries.

Measured on one day: 3,664 articles formed about 3,000 groups, 211 of them reported by two or more
outlets; with the stories they continue, about 300 groups went to the AI in 8 calls. Before code
grouping, the AI found 30 to 60 stories in the same volume.

### When a call fails

- **Network problems, rate limits, busy servers**: retried three times, waiting 15, 30 and 60
  seconds (or as long as the service asks).
- **An answer cut off at the output limit** (`max_output_tokens`), unreadable, or blocked by the
  model's filters: the call is split in two halves and each half is tried once. A smaller answer
  usually fits.
- **Still failing**: that call's articles are kept and tried first on the next run. If every call
  fails, the clock isn't moved and the whole run is retried. An answer that can't be used (a bug,
  or something strange from the model) is skipped the same way, without losing the other calls.

The reason for each failure is kept in the state file and shown on the website, under
"Collection and checks" on the Overview, with the day's collection numbers.

### What code checks in the AI's answer

| The AI says | Code checks |
|---|---|
| "These articles continue story X" | Code suggested X for these articles, or at least one headline shares two rare words, including a distinctive name, with the story's title or headlines. Otherwise the articles start a new story (with a title from their own headlines), so unrelated news isn't glued onto an old story about the same country |
| "This is a new story" | It has at least two articles; it isn't a story already tracked (see Duplicates); it isn't entertainment or sport (`story_terms` in `content_types.yaml`: a film festival, an actor's death, a transfer) |
| A report | The guardrails below |
| A title | The same checks; a title that fails is replaced by a real headline |

Everything code refuses is logged in `state/<site>/audit.json` with a kind: `rejected` (a sentence
failed a guardrail), `title`, `skipped` (a story not created or extended), `merged`, `correction`,
`commentary` or `info`. Only `rejected` sentences count as "removed by the checks" on the website.

### Status

Each story gets its status from dates, so running twice in one day gives the same result as once:

| Status | Meaning |
|---|---|
| **New** | First seen in the period |
| **Updated** | A new report: facts not collected before |
| **More coverage** | More outlets covered it, but they only repeated facts already collected |
| **Still tracked** | Nothing in the period |

A story with no coverage for `expire_days` is archived.

### Dates and corroboration

Every report is shown with the date its source **published** it: *On 12 Nov 2026, Reuters reported
that…*. The date is added by code from the article's own publication time; the AI never writes dates.

When another outlet reports facts already collected (a day late, say), it is not a new report. Code
adds the outlet to the earlier report as **also reported by AP (13 Nov)**, and the story shows as
*More coverage*, not *Updated*. A new report counts as a repeat when at least 70% of its words are
already in an earlier report and it adds no number and no name.

Dates written in the articles themselves ("on 8 November", "yesterday") are found by
`pipeline/mentioned_dates.py` and shown as *Dates in the reporting: Sun 8 Nov (3 outlets)*. Only
explicit dates within the two weeks before publication count; weekday names are ignored, since
"talks resume on Monday" may be the future.

## The checks

`pipeline/guardrails.py`, configured in `config/guardrails.yaml`. A sentence must pass all of them:

| # | Check | Rejects |
|---|---|---|
| 1 | Cites a real article by number | Sentences with no source, or a number that doesn't exist |
| 2 | Attributed with a reporting verb ("reported", "said", "according to"…) | Claims stated as fact |
| 3 | Every number appears in the cited articles (digits and number words) | Changed or invented figures |
| 4 | English sources: at least 70% of capitalised names appear in the cited articles. Translated sources: the sentence's countries must not all differ from the article's | Invented people, places, organisations; a story put in the wrong country |
| 5 | At least 65% of the meaningful words come from the cited articles (English sources) | The AI's own conclusions and paraphrase drift |
| 6 | No analysis words ("likely", "signals", "escalation", "unprecedented"…) unless the source used them | Assessment dressed as reporting |
| 7 | At most 45 words | Run-on summaries |

Numbers are compared as values: "15,000" matches "15 thousand", "15 mil" or Turkish "15 bin";
"$6.3bn" matches "6.3 billion"; for an article in another language, small numbers written as words
count too (Russian "две машины" backs "two cars"). Countries match across languages and forms:
"Chinese" is backed by "China", "Spain" by "España". The description of a state outlet that the
prompt asks for ("[7], a Russian state outlet, reported...") is not checked as content.

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
| Two tracked stories turn out to be one event | Merged after the run, when half the headlines of one pass the grouping test against the other's, in the same countries |
| A report repeats one already in the story, from the same outlets | Skipped |
| A report repeats facts already collected, from a new outlet | Added to the earlier report as "also reported by" |
| Several outlets report the same fact in the same call | The prompt asks for one report citing them all: "[4][9] reported that..." |
| An opinion, analysis or off-topic piece sits in a story | Removed from the story; a report resting only on such pieces is removed and logged |

The country condition matters for stories whose headlines are mostly in other languages: described
by only a few English words, two unrelated stories can look 50% similar by accident.

## Corrections

When grouping or placement goes wrong anyway, fix it in `config/geo/corrections.yaml` rather than in
the state files (which the daily run rewrites):

```yaml
remove_country:
  - {story: "Exact story title as shown on the website", country: spain}
place:
  - {story: "Exact story title", region: namerica, countries: [us, china]}
```

`remove_country`: on every run, articles and reports that mention that country and none of the
countries in the story's own title are taken out of the story and logged in the audit. They then
appear under the country on its region page, and a later run can start a proper story for them.

`place`: the story goes on that region's page with those countries, whatever the automatic
placement says (see [geography](geography.md)). An old rule does nothing once the story is archived.

## Ranking and the brief

- **Outlets** are counted per publisher (`config/publishers.yaml`), over the period the brief covers,
  including outlets that corroborated a report.
- **Reach** (Geopolitical): how many source regions' outlets reported the story (of seven: six
  regions plus international outlets). Shown on each card as "6 regions".
- **Most reported** and the **BLUF** (bottom line up front) are the five stories with new reports
  that have the widest reach, then the most outlets. Each BLUF line is the newest checked report for
  that story, or a real headline if none passed the checks. No new text is written for the BLUF.
- **Reported worldwide** (the Global page): up to 12 stories with coverage from at least three
  regions, widest reach first. They also stay on the page of the region they are about.
- **Flags**: *single source* (one outlet) and *state media only* (every source is government-run).
  Cards also show the mix of wire and state media sources.
- **Catch-up days**: `catch_up_days: {monday: 4}` makes Monday's brief cover Friday to Monday.
  Nothing is re-run; reports and articles carry the date they arrived, so the brief counts over a
  longer window.

## AI providers

`config/ai.yaml` selects the provider: `gemini` (Google's API, which has a free tier), `anthropic`, or
`mock` (no AI, for testing). Output is forced into a fixed JSON shape. The key is read from an
environment variable and never written anywhere.
