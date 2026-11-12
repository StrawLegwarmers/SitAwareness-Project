"""
manage_sources.py - add, disable, enable or remove a source without editing YAML by hand.

From the browser: open an issue with the "Add a source" or "Change a source" form on GitHub.
The "Manage sources" workflow runs this script with the issue's text, commits the change and
replies on the issue. In the Codespace you can run it directly:

  python pipeline/manage_sources.py add --site geo --name "Kyiv Independent" --url https://kyivindependent.com --where europe
  python pipeline/manage_sources.py disable --name "Naija News"
  python pipeline/manage_sources.py enable  --name "Naija News"
  python pipeline/manage_sources.py remove  --name "Naija News"

SAFETY. The issue text is typed by a person, so it's treated as untrusted:
  - the workflow only runs for the repository owner (anyone can open an issue on a public repo)
  - the text reaches this script through an environment variable, never pasted into a command
  - every value is checked (web address, language code) or picked from a fixed list (region),
    and written into the YAML as a quoted string, so it can't add keys or break the file
  - the feed is downloaded and must really be a feed before anything is saved
  - the whole file is validated afterwards; if anything is wrong, the change is undone
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

import yaml

from config import CONFIG, validate
from feeds import check_feed, discover_feed

# The issue form's choices -> the values sources.yaml uses
WHERE = {"global": ("geo", "region", "global"), "europe": ("geo", "region", "europe"),
         "north america": ("geo", "region", "namerica"), "asia & pacific": ("geo", "region", "asia"),
         "middle east & north africa": ("geo", "region", "mena"), "latin america & caribbean": ("geo", "region", "latam"),
         "africa": ("geo", "region", "africa"), "cyber: news": ("cyber", "section", "news"),
         "cyber: vendor research (intel)": ("cyber", "section", "intel"), "cyber: aviation": ("cyber", "section", "aviation"),
         "cyber: advisories": ("cyber", "section", "advisories")}
WHERE.update({v[2]: v for v in list(WHERE.values())})          # the short ids work too (europe, namerica, news...)
TYPES = {"international", "regional", "local", "wire", "specialist", "think-tank", "state-media", "government"}
URL_RE = re.compile(r"^https?://[^\s\"'<>{}|\\^`]+$", re.I)
LANG_RE = re.compile(r"^[a-z]{2,3}$")
MARK = "# Added from the browser"


def sources_path(site: str):
    return CONFIG / site / "sources.yaml"


def parse_issue(body: str) -> dict[str, str]:
    """An issue form arrives as '### Label' followed by the answer. Turn that into {label: answer}."""
    out, label, lines = {}, None, []
    for line in (body or "").splitlines():
        if line.startswith("### "):
            if label:
                out[label] = "\n".join(lines).strip()
            label, lines = line[4:].strip().lower(), []
        elif label:
            lines.append(line)
    if label:
        out[label] = "\n".join(lines).strip()
    return {k: ("" if v == "_No response_" else v) for k, v in out.items()}


def entries(site: str) -> list[tuple[int, dict]]:
    """(line number, source) for every one-line source entry in a site's sources.yaml."""
    found = []
    for i, line in enumerate(sources_path(site).read_text(encoding="utf-8").splitlines()):
        if line.lstrip().startswith("- {"):
            try:
                item = yaml.safe_load(line.strip()[2:])
            except yaml.YAMLError:
                continue
            if isinstance(item, dict) and item.get("name"):
                found.append((i, item))
    return found


def find(name: str) -> tuple[str, int, dict] | None:
    want = name.strip().lower()
    for site in ("geo", "cyber"):
        for i, item in entries(site):
            if str(item["name"]).strip().lower() == want:
                return site, i, item
    return None


def safe_write(site: str, text: str) -> str | None:
    """Write the file, validate it, and put the old one back if anything is wrong. Returns a problem or None."""
    path = sources_path(site)
    old = path.read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    try:
        yaml.safe_load(text)
        problems = validate(site)
    except Exception as ex:                      # noqa: BLE001 - any failure means: undo
        problems = [str(ex)]
    if problems:
        path.write_text(old, encoding="utf-8")
        return "; ".join(problems[:3])
    return None


def add(site_where: str, name: str, url: str, type_: str = "", lang: str = "", note: str = "", issue: str = "") -> str:
    name, url = (name or "").strip(), (url or "").strip()
    where = WHERE.get((site_where or "").strip().lower())
    if not where:
        return f"Not done: unknown region or section '{site_where}'."
    site, field, value = where
    if not name or len(name) > 80 or not name.isprintable():
        return "Not done: the name must be 1 to 80 ordinary characters on one line."
    if not URL_RE.match(url) or len(url) > 500:
        return "Not done: the address must start with https:// (or http://) and contain no spaces."
    lang = (lang or "en").strip().lower()
    if not LANG_RE.match(lang):
        return f"Not done: '{lang}' isn't a language code like en, es or fr."
    type_ = (type_ or "").strip().lower()
    if site == "geo" and type_ not in TYPES:
        type_ = "regional"
    if find(name):
        return f"Not done: a source called **{name}** already exists."
    # Is it a feed? If not, look for the site's feed (feeds.discover_feed).
    check = check_feed(url)
    feed, how = url, "the address is a feed"
    if not check["ok"]:
        found = discover_feed(url)
        if not found["feed"]:
            return (f"Not done: no feed found at {url} ({check['error'] or found['how']}). "
                    "Try the site's RSS address, or a Google News search feed (see docs/sources.md).")
        feed, check, how = found["feed"], found["check"], f"found the feed via {found['how']}"
    if any(item.get("feed") == feed for _, item in entries(site)):
        return f"Not done: that feed is already in config/{site}/sources.yaml."
    parts = [f"name: {json.dumps(name, ensure_ascii=False)}", f"feed: {json.dumps(feed)}", f"{field}: {value}"]
    if site == "geo":
        parts.append(f"type: {type_}")
    parts.append(f"lang: {lang}")
    stamp = datetime.now().strftime("%Y-%m-%d")
    note = "".join(ch for ch in re.sub(r"\s+", " ", (note or "").strip()) if ch.isprintable())[:120]
    parts.append(f"note: {json.dumps(('Added from the browser ' + stamp + (' (issue #' + issue + ')' if issue else '') + ('. ' + note if note else '')), ensure_ascii=False)}")
    line = "  - {" + ", ".join(parts) + "}"
    text = sources_path(site).read_text(encoding="utf-8").rstrip("\n")
    if MARK not in text:
        text += f"\n\n  {MARK}"
    problem = safe_write(site, text + "\n" + line + "\n")
    if problem:
        return f"Not done: the new line didn't pass the checks ({problem}). Nothing was changed."
    newest = check.get("newest") or "unknown"
    host = lambda u: re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", u.lower()))
    warn = (f"\n- **Check this:** the feed is on a different website ({host(feed)}) from the one you gave "
            f"({host(url)}). Sites sometimes move; if it's wrong, open a \"Change a source\" issue to remove it.") \
        if host(feed) != host(url) else ""
    return (f"Done: added **{name}** to `config/{site}/sources.yaml` ({field} `{value}`).\n\n"
            f"- Feed: {feed} ({how})\n- Test download: {check['items']} items, newest {newest}{warn}\n"
            f"- It will be read from the next daily run.")


def change(name: str, action: str) -> str:
    action = (action or "").strip().lower()
    if action not in ("disable", "enable", "remove"):
        return f"Not done: unknown action '{action}' (use Disable, Enable or Remove)."
    hit = find(name or "")
    if not hit:
        return f"Not done: no source called **{name}**. Names are listed on the website's Sources page."
    site, i, item = hit
    lines = sources_path(site).read_text(encoding="utf-8").splitlines()
    line = lines[i]
    if action == "remove":
        del lines[i]
    elif re.search(r"enabled:\s*(true|false)", line):
        lines[i] = re.sub(r"enabled:\s*(true|false)", f"enabled: {'false' if action == 'disable' else 'true'}", line)
    elif action == "disable":
        lines[i] = line[: line.rfind("}")] + ", enabled: false}"
    if lines[i:i + 1] == [line] and action != "remove":
        return f"Nothing to do: **{item['name']}** is already {'disabled' if action == 'disable' else 'enabled'}."
    problem = safe_write(site, "\n".join(lines) + "\n")
    if problem:
        return f"Not done: the change didn't pass the checks ({problem}). Nothing was changed."
    verb = {"disable": "disabled", "enable": "enabled", "remove": "removed"}[action]
    return f"Done: {verb} **{item['name']}** in `config/{site}/sources.yaml`. It takes effect from the next daily run."


def from_issue() -> str:
    """Called by the workflow. Title and body come from environment variables, never the command line."""
    title, body = os.environ.get("ISSUE_TITLE", ""), os.environ.get("ISSUE_BODY", "")
    f = parse_issue(body)
    issue = os.environ.get("ISSUE_NUMBER", "")
    if title.lower().startswith("add source"):
        return add(f.get("region (geopolitical) or section (cyber)", ""), f.get("name", ""), f.get("feed or website address", ""),
                   f.get("type (geopolitical only)", ""), f.get("language code", ""), f.get("note (optional)", ""), issue)
    if title.lower().startswith("change source"):
        return change(f.get("name", ""), f.get("what to do", ""))
    return "Not done: this issue doesn't look like a source request."


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Add, disable, enable or remove a source.")
    ap.add_argument("action", choices=["add", "disable", "enable", "remove", "from-issue"])
    ap.add_argument("--name")
    ap.add_argument("--url")
    ap.add_argument("--where", help="region (geo) or section (cyber): europe, namerica, news, intel...")
    ap.add_argument("--type", default="")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--out", help="also write the result to this file (the workflow posts it on the issue)")
    a = ap.parse_args()
    if a.action == "from-issue":
        result = from_issue()
    elif a.action == "add":
        result = add(a.where or "", a.name or "", a.url or "", a.type, a.lang)
    else:
        result = change(a.name or "", a.action)
    print(result)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(result + "\n")
    sys.exit(0)
