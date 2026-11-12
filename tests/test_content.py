import content


def test_opinion_by_address_and_headline():
    assert content.classify("https://e.com/opinion/2026/x", "A view")[0] == "opinion"
    assert content.classify("https://e.com/world/x", "Analysis: what next for the talks")[0] == "analysis"
    assert content.classify("https://e.com/world/x", "Talks resume")[0] == "news"


def test_offtopic_sections_only_on_the_geopolitical_site():
    assert content.classify("https://e.com/sport/football/x", "Cup final", site="geo")[0] == "offtopic"
    assert content.classify("https://e.com/sport/football/x", "Cup final", site="cyber")[0] == "news"


def test_news_tag_cancels_contradictory_tags():
    assert content.classify("https://e.com/world/x", "Interview", ["News", "Opinion"])[0] == "news"


def test_offtopic_story_filter():
    assert content.offtopic_story("Cairo International Film Festival opening", [], "geo")
    assert content.offtopic_story("Anthony Clark death", ["Actor Anthony Clark dies at 62", "Actor dies"], "geo")
    assert not content.offtopic_story("Iran-linked threat actor targets banks", ["Threat actor hits banks"], "geo")
    assert not content.offtopic_story("Spain general strike over housing", ["Spain strike"], "geo")
    assert not content.offtopic_story("Film festival", [], "cyber")


def test_split_story_drops_reports_resting_only_on_commentary():
    n = {"articles": [{"id": "a"}, {"id": "b"}], "reports": [{"articles": ["b"], "text": "x"}, {"articles": ["a"], "text": "y"}]}
    news, comment, keep, drop = content.split_story(n, {"a": "news", "b": "opinion"})
    assert [a["id"] for a in news] == ["a"] and [a["id"] for a in comment] == ["b"]
    assert [r["text"] for r in keep] == ["y"] and [r["text"] for r in drop] == ["x"]
