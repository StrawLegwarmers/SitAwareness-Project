import store


def article(n, title="A headline long enough to be fingerprinted for duplicates", published="2026-11-12T08:00:00+00:00"):
    return {"id": f"id{n}", "site": "geo", "source": "S", "outlet": "S", "url": f"https://e.com/{n}",
            "canonical_url": f"https://e.com/{n}", "title": title, "title_key": title.lower().replace(" ", ""),
            "summary": "", "published": published, "first_seen": published, "region": "europe", "section": None,
            "topics": "", "lang": "en", "type": "regional", "kind": "news"}


def test_insert_new_seen_and_duplicate_headline():
    conn = store.connect()
    conn.execute("DELETE FROM articles")
    assert store.insert_article(conn, article(1)) == "new"
    assert store.insert_article(conn, article(1)) == "seen"
    assert store.insert_article(conn, article(2)) == "dupe"          # same headline, other address


def test_pruned_articles_never_come_back_as_new():
    conn = store.connect()
    old = article(9, title="An undated item that the feed keeps for months", published="2020-01-01T00:00:00+00:00")
    store.insert_article(conn, old)
    assert store.prune(conn) >= 1
    assert store.insert_article(conn, old | {"published": "2026-11-12T08:00:00+00:00"}) == "seen"
