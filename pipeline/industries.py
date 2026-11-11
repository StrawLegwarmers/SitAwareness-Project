"""
industries.py - pick out the items that concern one industry (aviation...), from every source.

Plain keyword matching, configured in config/cyber/industries.yaml. No AI.
  topic words   : "is this about the industry?"
  concern words : "is it a security / safety / disruption issue?"
  exclude       : phrases that look like a match but aren't ("aircraft carrier")
Cyber news/research only needs a topic word anywhere (it's already about security), or in the
headline for broad industries (cyber_headline: true).
Everything else needs a topic word IN THE HEADLINE plus a concern word: matching summaries too
pulls in stories that only mention the industry in passing.
"""
from __future__ import annotations

import re

from config import CONFIG, load_yaml


def load_industries(site: str) -> list[dict]:
    """The industries, each with the shared concern words added."""
    path = CONFIG / site / "industries.yaml"
    if not path.exists():
        return []
    data = load_yaml(path)
    shared = data.get("concern") or []
    out = []
    for ind in data.get("industries") or []:
        ind = dict(ind)
        ind["concern"] = list(ind.get("concern") or shared) + list(ind.get("also_concern") or [])
        out.append(ind)
    return out


def matcher(words: list[str]):
    """One regex for a word list. ALL-CAPS words (FAA) match only in capitals; the rest ignore case."""
    caps = [w for w in words if w.isupper()]
    other = [w for w in words if not w.isupper()]
    parts = []
    if other:
        parts.append(re.compile(r"(?i)(?<![\w-])(?:" + "|".join(re.escape(w) for w in sorted(other, key=len, reverse=True)) + r")(?![\w-])"))
    if caps:
        parts.append(re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(w) for w in sorted(caps, key=len, reverse=True)) + r")(?![\w-])"))
    return lambda text: next((m.group(0) for p in parts for m in [p.search(text or "")] if m), None)


class Industry:
    def __init__(self, cfg: dict):
        self.id, self.name = cfg["id"], cfg["name"]
        self.topic = matcher(cfg.get("topic", []))
        self.concern = matcher(cfg.get("concern", []))
        self.exclude = matcher(cfg.get("exclude", [])) if cfg.get("exclude") else (lambda t: None)
        self.cyber_headline = bool(cfg.get("cyber_headline"))   # broad industries

    def matches(self, title: str, summary: str, already_security: bool) -> bool:
        """already_security = the item comes from a cyber news / research source."""
        head = self.exclude_phrases(title or "")
        text = f"{head} {self.exclude_phrases(summary or '')}"
        if already_security:
            return bool(self.topic(head if self.cyber_headline else text))
        return bool(self.topic(head)) and bool(self.concern(text))

    def exclude_phrases(self, text: str) -> str:
        """Remove excluded phrases before matching, so 'aircraft carrier' doesn't count as 'aircraft'."""
        while (m := self.exclude(text)):
            text = text.replace(m, " ")
        return text
