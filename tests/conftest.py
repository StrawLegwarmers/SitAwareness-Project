"""
Shared setup for the tests. Run them with:  python -m pytest -q

The tests never touch the network, an AI or your real database: SITAWARE_DB points at a
throwaway file and the AI provider is the offline "mock".
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
_TMP = Path(tempfile.mkdtemp(prefix="sitaware-test-"))
os.environ["SITAWARE_DB"] = str(_TMP / "test.db")
os.environ["SITAWARE_AI_USAGE"] = str(_TMP / "ai-usage.json")
os.environ["AI_PROVIDER"] = "mock"
os.environ.pop("MOCK_MAX_GROUPS", None)

import pytest  # noqa: E402


@pytest.fixture
def art():
    """Make an article record: art(1, "Headline", outlet="Reuters", lang="en", ...)."""
    def make(n: int, title: str, **kw) -> dict:
        a = {"id": f"a{n}", "title": title, "summary": kw.pop("summary", ""), "outlet": kw.pop("outlet", f"Outlet {n}"),
             "url": kw.pop("url", f"https://example.com/{n}"), "published": kw.pop("published", "2026-11-12T08:00:00+00:00"),
             "type": kw.pop("type", "regional"), "lang": kw.pop("lang", "en"), "section": kw.pop("section", None),
             "region": kw.pop("region", "europe"), "site": kw.pop("site", "geo"), "source": kw.pop("source", None)}
        a.update(kw)
        a["publisher"] = a["outlet"]
        a["group"] = a["region"]
        return a
    return make
