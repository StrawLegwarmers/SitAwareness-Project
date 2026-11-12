import pytest

import guardrails as g

ART = {"title": "Four cargo ships damaged by sea mines near Port Elm, Norland coast guard says",
       "summary": "The coast guard said the ships were still on fire, and two other vessels had been detained.", "lang": "en"}
VOTE = {"title": "Norland election: Unity Party vote share falls with 80 percent of ballots counted",
        "summary": "The party faces a heavy defeat in the regional vote.", "lang": "en"}
PL = {"title": "Strzelanina w Lindau: nie żyje 6 osób", "summary": "", "lang": "pl"}


@pytest.mark.parametrize("sentence, cited, reason", [
    ("[1] reported that with 80 percent of ballots counted, the Unity Party's vote share fell.", [VOTE], None),
    ("[1] reported the Norland coast guard said four cargo ships were damaged by sea mines near Port Elm.", [ART], None),
    ("[1] reported that 6 people died in a shooting in Lindau.", [PL], None),
    ("[1] reported the Unity Party faces a defeat that will permanently alter the political landscape.", [VOTE], "wording"),
    ("Sea mines damaged four cargo ships near Port Elm.", [ART], "no citation"),
    ("Cargo ships hit mines near Port Elm [1].", [ART], "not attributed"),
    ("[1] reported that six cargo ships hit mines near Port Elm.", [ART], "number"),
    ("[1] reported that 7 people died in a shooting in Lindau.", [PL], "number"),
    ("[1] reported that the navy of Estria condemned the attack near Port Elm.", [ART], "names"),
    ("[1] reported the coast guard said four ships damaged by sea mines could still be on fire.", [ART], "analysis word"),
])
def test_examples(sentence, cited, reason):
    ok, why = g.check(sentence, cited)
    assert ok == (reason is None), why
    if reason:
        assert why.startswith(reason)


@pytest.mark.parametrize("text, expected", [
    ("$6.3bn", {"6300000000"}), ("1,200 people", {"1200"}), ("80%", {"80"}), ("four tankers", {"4"}),
    ("15 thousand", {"15000"}), ("1.5 million", {"1500000"}), ("3 mil millones", {"3000000000"}),
    ("$2m", {"2000000"}), ("47th", {"47"}), ("one of the", set()),
])
def test_numbers(text, expected):
    assert g.numbers_in(text) == expected


def test_numbers_in_other_languages_only_for_foreign_sources():
    assert g.numbers_in("две машины", foreign=True) == {"2"}
    assert g.numbers_in("due to the storm") == set()                      # English "due" isn't Italian 2
    assert g.numbers_in("1.200 personas", foreign=True) == {"1200", "1.2"}
    assert g.numbers_in("٤٧ قتيلا") == {"47"}                                # Arabic-Indic digits


def test_thousands_written_in_another_language():
    ok, why = g.check("[1] reported that 15,000 soldiers were sent.", [{"title": "15 bin asker gönderildi", "lang": "tr"}])
    assert ok, why


def test_state_outlet_description_is_not_checked_as_content():
    ok, why = g.check("[7], a Russian state outlet, reported that Ukraine lost 40 tanks near Kharkiv.",
                      [{"title": "Ukraine lost 40 tanks near Kharkiv, ministry says", "lang": "en"}])
    assert ok, why


def test_country_names_match_across_languages():
    ok, why = g.check("[1] reported that Chinese leader Xi said reunification cannot be stopped.",
                      [{"title": "China's leader Xi says reunification cannot be stopped", "lang": "en"}])
    assert ok, why


def test_translated_report_in_the_wrong_country_is_caught():
    src = [{"title": "В Москве задержали двух мужчин", "lang": "ru"}]
    assert g.check("[1] reported that two men were arrested in Moscow.", src)[0]
    ok, why = g.check("[1] reported that Polish police arrested two men in Warsaw.", src)
    assert not ok and why.startswith("countries not in cited articles")


def test_too_long():
    ok, why = g.check("[1] reported " + "that ships were damaged near Port Elm " * 8 + ".", [ART])
    assert not ok and why.startswith("too long")
