import cluster


def heads(arts):
    return [[a["title"] for a in grp] for grp in cluster.cluster(arts, "geo")]


def test_little_words_of_other_languages_are_ignored():
    assert not cluster.tokens("los del para con según") and not cluster.tokens("след при над заради")


def test_same_event_is_grouped(art):
    arts = [art(1, "Russia and Ukraine agree prisoner exchange after Abu Dhabi talks", outlet="A"),
            art(2, "Russia, Ukraine strike prisoner exchange deal in Abu Dhabi talks", outlet="B"),
            art(3, "Hegseth reprimanded by guard at Tomb of the Unknown Soldier", outlet="C"),
            *[art(10 + i, f"Unrelated headline number {i} about farming yields", outlet=f"X{i}") for i in range(30)]]
    groups = heads(arts)
    big = [g for g in groups if len(g) > 1]
    assert len(big) == 1 and len(big[0]) == 2 and all("Abu Dhabi" in t for t in big[0])


def test_common_words_without_a_shared_name_dont_group(art):
    arts = [art(1, "Ataque armado en Mérida deja una persona muerta", lang="es", outlet="A"),
            art(2, "Ataque israelí a hospital del sur de Gaza deja 6 personas muertas", lang="es", outlet="B"),
            *[art(10 + i, f"Otra noticia {i} sobre agricultura", lang="es", outlet=f"X{i}") for i in range(30)]]
    assert all(len(g) == 1 for g in heads(arts)[:2])


def test_countries_must_not_clash(art):
    arts = [art(1, "Migrant boat sinks off Crete, Greece says 13 dead", outlet="A"),
            art(2, "Migrant boat sinks off Senegal coast, 13 dead", outlet="B"),
            *[art(10 + i, f"Unrelated headline number {i} about farming yields", outlet=f"X{i}") for i in range(30)]]
    assert all(len(g) == 1 for g in heads(arts)[:2])


def test_story_continuation_needs_a_distinctive_name(art):
    story = {"id": "s", "title": "Zelenskyy Starshield satellite restrictions",
             "articles": [art(1, "Guerre en Ukraine: Starshield, la Russie et les satellites", lang="fr")]}
    arts = [art(2, "Guerre en Ukraine: les émissaires américains vont rencontrer Poutine en Russie", lang="fr"),
            art(3, "Zelenskyy says Starshield satellite speed caps helped Russian drones"),
            *[art(10 + i, f"Unrelated headline number {i} about farming yields") for i in range(2000)]]   # a day's worth
    idx = cluster.index_for(arts + story["articles"])
    tracked = cluster.Stories([story], idx, "geo")
    assert tracked.match([arts[0]])[0] is None
    assert tracked.match([arts[1]])[0] is story
    assert cluster.related(idx, [arts[1]], story, "geo") and not cluster.related(idx, [arts[0]], story, "geo")


def test_index_treats_words_common_in_a_language_as_not_rare():
    docs = [{"commonword", f"w{i}"} for i in range(200)]
    idx = cluster.Index(docs, ["xx"] * 200)
    assert "commonword" not in idx.rare({"commonword", "w1"}, "xx")
