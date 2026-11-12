from mentioned_dates import dates_in

PUB = "2026-11-12T08:00:00+00:00"


def test_explicit_dates_and_yesterday():
    assert dates_in("Prisoners swapped on Nov. 8", PUB) == ["2026-11-08"]
    assert dates_in("El 10 de noviembre de 2026 hubo protestas", PUB) == ["2026-11-10"]
    assert dates_in("Yesterday's attack killed 5", PUB) == ["2026-11-11"]


def test_future_and_old_dates_are_ignored():
    assert dates_in("Talks resume on 20 November", PUB) == []
    assert dates_in("On 8 November 2025, a year ago", PUB) == []
    assert dates_in("Prices may 5 times", PUB) == []


def test_bad_publication_date_is_harmless():
    assert dates_in("on 8 November", "not a date") == []
