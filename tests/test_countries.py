import countries

G = countries.load("geo")


def place(title, sources=None, hint=None):
    return G.place(G.score([], title), "global", title, hint, sources)


def test_entities_place_stories_without_country_names():
    p = place("Nvidia CEO questioned by FBI over spy affair")
    assert p["region"] == "namerica" and p["countries"][0] == "us"
    assert place("Building collapse in New York City kills 3")["region"] == "namerica"


def test_no_majority_goes_to_the_lead_country():
    assert place("France summons Iran envoy over supermarket fridge hack")["region"] == "europe"


def test_three_regions_go_to_global():
    assert place("G20 leaders from Brazil, India, South Africa and Germany meet")["region"] == "global"


def test_hyphenated_country_lists_count():
    p = place("New round of Russia-US-Ukraine trilateral talks begins in Abu Dhabi")
    assert set(p["countries"]) >= {"russia", "us", "ukraine"} and p["region"] == "europe"


def test_venues_count_a_quarter():
    assert G.find("talks in Abu Dhabi")["uae"] == 0.25


def test_no_country_named_local_news_follows_its_outlets():
    from collections import Counter
    assert place("Police chief sacked over kidnappings", Counter({"africa": 3}))["region"] == "africa"
    assert place("Police chief sacked over kidnappings", Counter({"africa": 1, "europe": 1}))["region"] == "global"
    assert place("Oil prices fall")["region"] == "global"


def test_dateline_wins():
    assert place("Poland: Krakow shooting suspect charged")["lead"] == "poland"


def test_companies_count_half():
    assert G.find("Nvidia shares fall")["us"] == 0.5


def test_case_sensitive_matching():
    assert "us" not in G.find("tell us more")
