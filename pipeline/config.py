"""
config.py - reads the YAML files in config/ and checks they make sense.

Keeping configuration in plain YAML files (instead of inside the code) is what
makes the project customizable: adding a source, a region or a whole new site
means editing a text file, not Python.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent       # the repo folder
CONFIG = ROOT / "config"

# Allowed values. If you add a region or type, add it here too, and the checker will accept it.
GEO_REGIONS = {"global", "namerica", "latam", "europe", "mena", "africa", "asia"}
GEO_TYPES = {"wire", "international", "regional", "local", "think-tank", "state-media", "specialist", "government"}
CYBER_SECTIONS = {"news", "intel", "aviation", "advisories"}
MARKETS_SECTIONS = {"news", "official", "analysis"}


def sites() -> list[str]:
    """Every folder in config/ that has a sources.yaml is a site (geo, cyber, ...)."""
    return sorted(p.parent.name for p in CONFIG.glob("*/sources.yaml"))


def load_yaml(path) -> dict:
    """Read a YAML file. A typo gives a short, readable message instead of a long traceback."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as ex:
        mark = getattr(ex, "problem_mark", None)
        where = f"line {mark.line + 1}" if mark else "somewhere"
        raise SystemExit(
            f"\nThere's a typo in {path.relative_to(ROOT)} at {where}: {getattr(ex, 'problem', ex)}.\n"
            "Most often it's indentation: every source line starts with exactly 2 spaces, then '- {'.\n"
            "Also check for a missing quote or curly brace on that line or the one above.")


def load_site(site: str) -> dict:
    """config/<site>/site.yaml: name, AI focus, groups, limits."""
    s = load_yaml(CONFIG / site / "site.yaml")
    s["id"] = site
    return s


def load_publishers() -> dict[str, str]:
    """config/publishers.yaml turned around: {"BBC Africa": "BBC", ...}. Missing file = no grouping."""
    path = CONFIG / "publishers.yaml"
    groups = load_yaml(path) if path.exists() else {}
    return {source: publisher for publisher, sources in groups.items() for source in (sources or [])}


def load_ai() -> dict:
    """config/ai.yaml: which AI provider and model to use."""
    return load_yaml(CONFIG / "ai.yaml")


def load_sources(site: str, include_disabled: bool = False) -> list[dict]:
    """Load config/<site>/sources.yaml and return the list of sources."""
    data = load_yaml(CONFIG / site / "sources.yaml")
    out = []
    for s in data.get("sources", []):
        s = dict(s)
        s["site"] = site
        s.setdefault("enabled", True)
        s.setdefault("topics", [])
        if include_disabled or s["enabled"]:
            out.append(s)
    return out


def validate(site: str) -> list[str]:
    """Return a list of human-readable problems in a site's sources.yaml (empty list = all good)."""
    problems, seen = [], {}
    for i, s in enumerate(load_sources(site, include_disabled=True), start=1):
        label = f"{site} #{i} '{s.get('name', '?')}'"
        if not s.get("name"):
            problems.append(f"{label}: missing 'name'")
        if not s.get("feed") and not s.get("site_only"):
            problems.append(f"{label}: missing 'feed' (use site_only: true for links without a feed)")
        if s.get("feed"):
            if s["feed"] in seen:
                problems.append(f"{label}: same feed as '{seen[s['feed']]}'")
            seen[s["feed"]] = s.get("name")
        if site == "geo":
            if s.get("region") not in GEO_REGIONS:
                problems.append(f"{label}: region '{s.get('region')}' not in {sorted(GEO_REGIONS)}")
            if s.get("type") and s["type"] not in GEO_TYPES:
                problems.append(f"{label}: type '{s['type']}' not in {sorted(GEO_TYPES)}")
        if s.get("kind") and s["kind"] not in ("news", "opinion", "analysis"):
            problems.append(f"{label}: kind '{s['kind']}' must be news, opinion or analysis")
        if site == "cyber" and s.get("section") not in CYBER_SECTIONS:
            problems.append(f"{label}: section '{s.get('section')}' not in {sorted(CYBER_SECTIONS)}")
        if site == "markets" and s.get("section") not in MARKETS_SECTIONS:
            problems.append(f"{label}: section '{s.get('section')}' not in {sorted(MARKETS_SECTIONS)}")
    return problems
