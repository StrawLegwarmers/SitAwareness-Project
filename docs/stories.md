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
3. **Choose what goes to the AI**: every group reported by two or more outlets, every group
   (even one article) that continues a tracked story, and on Cyber, research from the labs and
   agencies listed in `single_source_stories` (see [cyber](cyber.md#single-source-research)). Biggest first, about 40 groups per call
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

### How accurate the grouping is

`tests/data/grouping_day.json.gz` holds one real day of 6,223 headlines. For 722 of them, a person
checked which event each reports (about 45 events of 2 to 40 headlines, in 15 languages, and about
230 headlines that are their own event, including look-alikes such as separate drone strikes on the
same night). `python pipeline/evaluate_grouping.py` scores code's grouping against them:

| | Score | Meaning |
|---|---|---|
| Precision | 0.968 | Groups are rarely a mix of different events |
| Recall | 0.563 | An event's headlines often end up in several groups, mostly across languages and wordings |

Precision matters more: a mixed group misleads the AI, while split groups are joined by the AI
("If two groups are the same event, return one story") and by later continuations. The thresholds
were tuned on this day (`--tune` tries 90 combinations; the earlier settings scored 0.957 and
0.561). Lower thresholds raised recall to 0.60 but let look-alikes in (precision 0.93); joining
groups that share one rare name raised recall to 0.7 but dropped precision to 0.72. Neither was
adopted. The tests fail if precision falls below 0.95 or recall below 0.5. `--mistakes` lists the
worst merges and splits; labels are judgment calls and can be edited in the file.

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
| "These articles continue story X" | Checked group by group: each of code's groups in the answer must be one code suggested for X, or have a headline sharing two rare words, including a distinctive name, with the story's title or headlines. A group that fails is left out (and any report citing it is refused), so one unrelated headline can't ride along with a correct group. If every group fails, the articles start a new story |
| "This is a new story" | It has at least two articles (one is enough for research from a source in `single_source_stories`, unless the headline is product news); it isn't a story already tracked (see Duplicates); it isn't entertainment or sport (`story_terms` in `content_types.yaml`); and its **topic** is one the site keeps (see Topics) |
| A title for a tracked story | Ignored: titles of running stories come from code (see Titles) |
| A report | The guardrails below |
| A title for a new story | The same checks; a title that fails is replaced by a real headline. It becomes the story's wider-story name |

Everything code refuses is logged in `state/<site>/audit.json` with a kind: `rejected` (a sentence
failed a guardrail), `title`, `skipped` (a story not created or extended), `dropped` (a group of two
or more outlets the AI returned no story for: usually judged off-topic), `merged`, `correction`,
`commentary` or `info`. Only `rejected` sentences count as "removed by the checks" on the website.
`python pipeline/narratives.py --site cyber --audit` answers "why isn't X on the site?".

### Topics

The AI labels every story with one topic from a fixed list (`TOPICS` in `narratives.py`, rule 13 of
the prompt): conflict, security, diplomacy, politics, elections, justice, economy, energy,
infrastructure (outages), migration, humanitarian, disaster, health-emergency, cyber,
technology-policy, crime, business-strategic, markets-strategic, and the ones no site keeps:
business, markets, health, science, technology, sport, entertainment, culture, celebrity,
lifestyle, weather, other. Each site lists the topics it keeps (`topics` in `site.yaml`); a new
story with another topic isn't created, and the audit log says which topic. Company and market
news stays only when the articles tie it to governments, sanctions, export controls, national
security, conflict or critical supply chains (business-strategic, markets-strategic). Choosing a
label is more reliable than remembering a list of exclusions. A story without a topic is kept: the
other filters still apply.

### Titles: the latest headline, under its wider story

A story has two names:

- its **wider story** (`label`): set on its first day from the AI's topic label ("Nvidia CEO affair
  and espionage claims"), and kept. Code places the story by it, so it doesn't move region daily.
- its **title**: each day, the real headline that best represents that day's coverage, picked by
  code (`cluster.lead_headline`): the English headline that matches the most other outlets'
  headlines that day, wires and international outlets first on a tie, never a live blog, explainer
  or question, and never a state outlet's headline when another qualifies. It needs at least three
  articles that day and backing from at least 40% of the day's other outlets (two at least);
  otherwise the title stays as it was. So a single unrelated headline filed under the story can
  never become its title. Earlier titles are kept in `previous_titles`.

The website shows the title first and, for a story running since before the period, its wider
story in a small box above it, which opens the earlier reporting. The AI never renames a story.

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

Story **names** written by the AI are checked the same way; one that fails is replaced by a real
headline. Titles of running stories are real headlines picked by code (see Titles).

Every removed sentence is logged in `state/<site>/audit.json` with the reason, kept 7 days, and
counted at the foot of the website. Run `python pipeline/guardrails.py` to see the checks applied to
examples.

## Duplicates

| Situation | What happens |
|---|---|
| The AI proposes a "new" story that matches one already tracked | Merged into the existing one, if both have at least 6 meaningful words, share at least 3, overlap by at least 50%, and have at least one country in common |
| Two tracked stories turn out to be one event | Merged after the run, when half the headlines of one pass the grouping test against the other's, in the same countries |
| Two stories the word test can't link (other languages, a big day when every headline says "Microsoft") | Code lists pairs updated today, one of them new, whose core names overlap (rare capitalised words in the wider-story name or in two of the day's headlines, not countries, not names found in more than 6 stories) and whose countries don't clash: at most 30 pairs. One AI call answers "same event?" for each (`config/prompts/duplicates.md`); code merges only the pairs it asked about and the AI said yes to, into the older story |
| A report repeats one already in the story, from the same outlets | Skipped |
| A report repeats facts already collected, from a new outlet | Added to the earlier report as "also reported by" |
| Several outlets report the same fact in the same call | The prompt asks for one report citing them all: "[4][9] reported that..." |
| An opinion, analysis or off-topic piece sits in a story | Removed from the story; a report resting only on such pieces is removed and logged |

The country condition matters for stories whose headlines are mostly in other languages: described
by only a few English words, two unrelated stories can look 50% similar by accident.

## Maintenance

`pipeline/maintenance.py`, also on the Actions tab as **Maintenance** (Run workflow; tick *apply* to
make the changes, leave it unticked to only list them):

- **clean** finds stories that mix unrelated events, from before code checked continuations
  (a minister's resignation under a migrant-boat story). For each story with four or more
  articles: its core is its title and the articles from its first day; every other article must
  share something with the core, directly or through another kept article (a country in any
  language, two rare words, or one rare name). Articles sharing nothing are suspects; the AI then
  checks the suspects (`config/prompts/cleanup.md`), and only those both agree on are moved: two or
  more about the same thing become their own story, with the reports that cite only them; single
  ones leave the story. Everything moved is in the audit log (kind `cleanup`).
- **labels** refreshes the wider-story names of stories running more than a day. The AI proposes
  a neutral topic name covering all of a story's headlines (`config/prompts/labels.md`); code keeps
  it only if its names and numbers come from the headlines and it fits at least half of the
  story's English headlines (a shared rare word that isn't a country, and no clash of countries),
  and not noticeably worse than the old name. Each change is in the audit log (kind `title`).

## Corrections

When grouping or placement goes wrong anyway, fix it in `config/geo/corrections.yaml` rather than in
the state files (which the daily run rewrites):

```yaml
remove_country:
  - {story: "Exact story title as shown on the website", country: spain}
place:
  - {story: "Exact story title", region: namerica, countries: [us, china]}
remove_headline:     # one headline that doesn't belong, with any report resting only on it
  - {story: story-id, headline: "FSB foils terror plot at Stavropol"}
merge:               # into the first one listed
  - {stories: [story-id, other-story-id]}
hide:                # off the site (archived, marked hidden)
  - {story: story-id}
```

A story can be named by its id, its title or its wider-story name; the id never changes (it is
shown in the audit log and in `state/geo/narratives.json`).

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
