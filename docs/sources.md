# Sources

Each site reads the feeds listed in `config/<site>/sources.yaml`: about 255 for Geopolitical and 75
for Cyber. A source is one line:

```yaml
  - {name: Example News, feed: "https://example.com/feed/", region: europe, type: regional, lang: en}
```

## Fields

| Field | Values | Meaning |
|---|---|---|
| `name` | text | Shown on the site. Must be unique |
| `feed` | address | The RSS or Atom address (not the home page) |
| `region` | `global`, `namerica`, `latam`, `europe`, `mena`, `africa`, `asia` | Geopolitical: the region its outlet covers (used for reach, and to file local news that names no country) |
| `section` | `news`, `intel`, `aviation`, `advisories` | Cyber: cyber news, vendor research, aviation trade press, or advisory bulletins (bulletins are listed but never sent to the AI) |
| `type` | `wire`, `international`, `regional`, `local`, `specialist`, `think-tank`, `state-media`, `government` | State media claims are always attributed, never stated as fact. Think tanks count as analysis |
| `kind` | `news`, `opinion`, `analysis` | Optional: overrides how the source's articles are labelled ([collection](collection.md#opinion-and-analysis)) |
| `lang` | `en`, `es`, `fr`... | Language code. The AI reads every language and writes English |
| `topics` | list | Optional tags for a running theme |
| `enabled` | `true` / `false` | `false` keeps the source on file without fetching it |
| `site`, `site_only` | address, `true` | A useful link that has no feed |
| `note` | text | Why a source is disabled, where it came from |

Feeds from one organisation (an outlet's world, Europe and Africa feeds) are tied together in
`config/publishers.yaml`, so they count as one outlet.

## Finding and testing feeds

```bash
python pipeline/check_sources.py                      # test every enabled source
python pipeline/check_sources.py --site cyber --all   # one site, including disabled sources
python pipeline/check_sources.py --discover https://example.com
```

`--discover` looks for a website's feed: first whether the address is already a feed, then the
`<link rel="alternate">` tag that sites use to advertise their feed, then common paths such as
`/feed/` and `/rss.xml`.

**No feed?** A Google News search feed often works:
`https://news.google.com/rss/search?q=site:example.com&hl=en-US&gl=US&ceid=US:en`. Its items are
unwrapped so the real publisher and headline are recorded.

## The Sources page

**Reference → Sources** on the website lists every source, refreshed by each daily run:

| Status | Meaning |
|---|---|
| Failing | The last download failed. Shows the error (for example `HTTP 410`, `not a feed`), how many runs in a row, and when it last worked. After 7 days of failures the daily run turns it off automatically, with a dated note ([operations](operations.md#feeds-that-keep-failing)) |
| Quiet this week | Downloads work but nothing was published in 7 days |
| Not fetched yet | Added since the last run |
| Working | Articles in the last 7 days, and the newest |
| Disabled / No feed | Kept on file, not fetched |

## Adding or changing sources from the browser

A static website can't edit files, so requests go through GitHub:

1. **Reference → Sources → Add a source** opens a short GitHub form: name, address (a feed or just a
   website), region or section, type and language. Next to each source, **Disable** or **Enable**
   opens the "Change a source" form with the name filled in.
2. Submitting the form opens an issue, and the **Manage sources** workflow starts automatically.
   It runs `pipeline/manage_sources.py`, which downloads the address to check it's a working feed
   (or finds the site's feed), adds, disables, enables or removes the line in the right
   `sources.yaml`, validates the whole file, and commits.
3. It replies on the issue ("Done: added … 90 items, newest 2 hours ago") and closes it. If anything
   is wrong it explains why and changes nothing. If the feed it found is on a different website from
   the address given, the reply says so.

The same operations from a terminal:

```bash
python pipeline/manage_sources.py add --where europe --name "Example News" --url https://example.com --type regional
python pipeline/manage_sources.py disable --name "Example News"
python pipeline/manage_sources.py enable  --name "Example News"
python pipeline/manage_sources.py remove  --name "Example News"
```

### Safeguards

- **Owner only.** The workflow acts only when the issue's author is the repository owner or a
  collaborator with write access. Anyone else's request is ignored: nothing runs.
- **No script injection.** The issue's title and text reach Python through environment variables and
  are never placed inside a shell command.
- **Checked values.** The address must be a web address, the language a short code, and the region
  one of the form's choices. Names are written as quoted strings, so they can't add settings or break
  the file.
- **Validate or undo.** After every edit the whole file is loaded and validated; any problem restores
  the previous version.
- **Everything is a commit,** labelled with the request number, so any change can be reverted.

To restrict the robot to the owner alone, change the workflow's `if:` line to
`github.event.issue.author_association == 'OWNER' && …`. If strangers open many requests, use
**Settings → Moderation options → Interaction limits**.
