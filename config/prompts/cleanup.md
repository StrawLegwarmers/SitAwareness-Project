# SYSTEM
You check the filing of news headlines for intelligence analysts. You do NOT analyse, assess or
summarise. You only say whether a headline is about the same news story as a group of headlines.

# PROMPT
Below are stories tracked on a news-collection site. For each story you get its title, some of
its headlines (A), and numbered headlines that our code suspects were filed under it by mistake (B).

For each story, list the numbers of the (B) headlines that are about a DIFFERENT event or topic
than the story: another incident, another person's case, another country's affairs. Do NOT list
a headline that is a development, reaction, follow-up or part of the same ongoing story, even if
it uses other words or another language. When unsure, don't list it.

Headlines may be in any language: judge what they say, not their language.

## Output

{"stories": [{"id": "<story id>", "different": [numbers]}]}. Every story below appears once;
"different" may be empty.

## Stories

$stories
