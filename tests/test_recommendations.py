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
