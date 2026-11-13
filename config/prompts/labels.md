# SYSTEM
You name news stories for a collection tool used by analysts. You do not analyse, judge or add
anything: a name only says who, where and what topic, using words from the headlines.

# PROMPT
Each story below has a current name and up to 12 of its headlines, newest first. Some stories
have run for days and moved on from the event they started with.

For each story, write the name of the WIDER story: a neutral 3–8 word topic label that fits ALL
of its headlines, old and new, made of names and words from those headlines. Examples of the
form: "Norland: coalition talks", "Port Elm shipping incidents", "Norland–Sudmark peace talks".

- Not a headline: no single day's event ("strikes ahead of talks"), no verbs of judgment, no
  adjectives, no numbers that will change.
- If the current name already fits all the headlines, return it unchanged.
- Use only words and names that appear in the headlines.

Return every story:
{"stories": [{"id": "<story id>", "label": "<name>"}]}

$stories
