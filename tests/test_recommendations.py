"""Recommendation quality: worked examples, invariants and explanations."""
import json
import random
import pytest
from watchtogether.graph import GraphStore, PARENTS, ROOT
from watchtogether.recommender import Recommender
from watchtogether.examples import EXAMPLES, as_rows
import reference
from conftest import auth

STARTER = ROOT / "data/catalog.json"


@pytest.fixture(scope="module")
def graph():
    return GraphStore(STARTER)


@pytest.fixture(scope="module")
def recommender(graph):
    return Recommender(graph)


@pytest.fixture(scope="module")
def truth(graph):
    return reference.load(STARTER, PARENTS)


@pytest.mark.parametrize("example", EXAMPLES, ids=[example["name"] for example in EXAMPLES])
def test_example_groups_get_the_expected_shortlist(recommender, example):
    movies = recommender.rank(as_rows(example["members"]))
    assert [movie["title"] for movie in movies] == example["expected"]
    assert [movie["score"] for movie in movies] == example["expected_scores"]


def test_conflict_dislike_vetoes_the_best_match(recommender):
    example = next(item for item in EXAMPLES if item["name"] == "conflicting tastes")
    titles = {movie["title"] for movie in recommender.rank(as_rows(example["members"]), limit=100)}
    assert titles.isdisjoint(example["vetoed"])
    # Without Ben's dislike, Get Out is the top pick, so the veto is what removed it.
    relaxed = [dict(member, dislikes=[]) for member in example["members"]]
    assert recommender.rank(as_rows(relaxed))[0]["title"] == "Get Out"


def test_balanced_film_outranks_one_sided_favourites(recommender):
    example = next(item for item in EXAMPLES if item["name"] == "balanced beats one-sided")
    everything = {movie["title"]: movie for movie in recommender.rank(as_rows(example["members"]), limit=100)}
    best = everything[example["expected"][0]]
    for title in example["below"]:
        one_sided = everything[title]
        assert sorted(match["match"] for match in one_sided["matches"]) == [33, 100]
        assert one_sided["score"] == pytest.approx(46.6667)
        assert one_sided["score"] < best["score"]


def test_examples_through_the_api(client):
    for example in EXAMPLES:
        people = [client.post("/api/groups", json={"title": example["name"], "nickname": example["members"][0]["nickname"]}).json()]
        gid = people[0]["group_id"]
        for member in example["members"][1:]:
            people.append(client.post(f"/api/groups/{gid}/members", json={"nickname": member["nickname"]}).json())
        for person, member in zip(people, example["members"]):
            saved = client.put(f"/api/groups/{gid}/profile", headers=auth(person),
                               json={"likes": member["likes"], "dislikes": member["dislikes"]})
            assert saved.status_code == 200, saved.text
        result = client.post(f"/api/groups/{gid}/recommendations", headers=auth(people[0]))
        if example["expected"]:
            assert [movie["title"] for movie in result.json()["recommendations"]] == example["expected"]
        else:
            assert result.status_code == 409 and "No film matches everyone" in result.text


def random_groups(graph, seed, count):
    """Seeded random groups of 2, 4 and 8 people over a catalogue.

    Friends share some taste: each group draws a small pool of genres, people and films,
    every member likes a few of those plus maybe one personal pick, and some members
    dislike something from the whole catalogue.
    """
    rng = random.Random(seed)
    genres = sorted(key for key, value in graph.entities.items() if value["kind"] == "genre")
    people = sorted(key for key, value in graph.entities.items() if value["kind"] == "person")
    films = sorted(graph.movies)
    anything = genres + people + films
    for number in range(count):
        size = [2, 4, 8][number % 3]
        shared = rng.sample(genres, 3) + rng.sample(people, 2) + rng.sample(films, 2)
        members = []
        for index in range(size):
            likes = rng.sample(shared, rng.randint(1, 3)) + rng.sample(anything, rng.choice([0, 0, 1]))
            likes = list(dict.fromkeys(likes))
            dislikes = [item for item in rng.sample(anything, rng.choice([0, 0, 1, 2])) if item not in likes]
            members.append({"id": f"m{index}", "nickname": f"M{index}", "likes": likes, "dislikes": dislikes})
        yield members


def rows(members):
    return [{**member, "likes": json.dumps(member["likes"]), "dislikes": json.dumps(member["dislikes"])} for member in members]


GROUPS = 90


def test_random_groups_match_the_reference_rules(graph, recommender, truth):
    compared = with_results = 0
    for members in random_groups(graph, seed=2026, count=GROUPS):
        expected = reference.rank(truth, members)
        actual = recommender.rank(rows(members))
        assert [movie["id"] for movie in actual] == [movie["id"] for movie in expected]
        assert [movie["score"] for movie in actual] == [movie["score"] for movie in expected]
        for got, want in zip(actual, expected):
            assert [match["match"] for match in got["matches"]] == [match["match"] for match in want["matches"]]
        compared += 1
        with_results += bool(actual)
    assert compared == GROUPS and with_results > GROUPS // 3


def test_every_pick_matches_a_like_of_every_member(graph, recommender, truth):
    checked = 0
    for members in random_groups(graph, seed=7, count=GROUPS):
        for movie in recommender.rank(rows(members)):
            assert len(movie["matches"]) == len(members)
            for member in members:
                assert any(truth.liked(taste, movie["id"]) for taste in member["likes"]), (movie["title"], member)
                checked += 1
    assert checked > 200


def test_no_pick_breaks_anyones_dislike(graph, recommender, truth):
    checked = 0
    for members in random_groups(graph, seed=11, count=GROUPS):
        for movie in recommender.rank(rows(members), limit=100):
            for member in members:
                for taste in member["dislikes"]:
                    assert not truth.disliked(taste, movie["id"]), (movie["title"], member["nickname"], taste)
                    checked += 1
    assert checked > 200


def test_each_dislike_kind_is_a_hard_veto(graph, recommender):
    likes = ["genre:comedy", "genre:drama", "genre:adventure"]
    for dislike, banned in [("genre:romance", lambda film: "romance" in film["genres"] or "romantic-comedy" in film["genres"]),
                            ("genre:animation", lambda film: {"animation", "anime"} & set(film["genres"])),
                            ("person:tom-hanks", lambda film: "Tom Hanks" in film["cast"] + film["directors"]),
                            ("film:forrest-gump-1994", lambda film: film["id"] == "film:forrest-gump-1994")]:
        members = [{"id": "a", "nickname": "A", "likes": likes, "dislikes": []},
                   {"id": "b", "nickname": "B", "likes": likes, "dislikes": [dislike]}]
        open_list = recommender.rank(rows([dict(members[0]), dict(members[0], id="b", nickname="B")]), limit=100)
        assert any(banned(movie) for movie in open_list), dislike  # the dislike has something to remove
        assert not any(banned(movie) for movie in recommender.rank(rows(members), limit=100)), dislike
