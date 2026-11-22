"""The same checks on the 10,000-film Wikidata catalogue (data/wikidata.json)."""
import time
import pytest
from watchtogether.graph import GraphStore, ROOT
from watchtogether.recommender import Recommender
import reference
from test_recommendations import random_groups, rows

BIG = ROOT / "data/wikidata.json"
pytestmark = pytest.mark.skipif(not BIG.exists(), reason="imported catalogue not present")

# Words that mark a genre as a kind of the disliked one, written out independently of graph.py.
FAMILIES = {
    "genre:horror": lambda genre: "horror" in genre.split("-") or genre.split("-")[0] in
    {"slasher", "zombie", "vampire", "werewolf", "splatter", "gore", "cannibal"},
    "genre:western": lambda genre: "western" in genre.split("-"),
    "genre:comedy": lambda genre: "comedy" in genre.split("-") or genre in
    {"slapstick", "parody", "mockumentary", "farce", "satire", "satirical", "tragicomedy"},
    "genre:science-fiction": lambda genre: "science-fiction" in genre or genre in
    {"cyberpunk", "biopunk", "steampunk", "dystopian", "post-apocalyptic", "alien-invasion", "time-travel", "space-opera"},
}


@pytest.fixture(scope="module")
def big():
    graph = GraphStore(BIG)
    return graph, Recommender(graph), reference.load(BIG, graph.genre_parents)


@pytest.mark.parametrize("dislike", sorted(FAMILIES))
def test_dislike_removes_the_whole_genre_family(big, dislike):
    graph, recommender, _ = big
    likes = ["genre:drama", "genre:action", "genre:romance", "genre:thriller", "genre:fantasy"]
    free = [{"id": "a", "nickname": "A", "likes": likes, "dislikes": []},
            {"id": "b", "nickname": "B", "likes": likes, "dislikes": []}]
    in_family = lambda movie: any(FAMILIES[dislike](genre) for genre in movie["genres"])
    tagged_only_as_subgenre = lambda movie: in_family(movie) and dislike[6:] not in movie["genres"]
    everything = recommender.rank(rows(free), limit=len(graph.movies))
    assert any(tagged_only_as_subgenre(movie) for movie in everything)  # the leak this guards against
    vetoed = [free[0], dict(free[1], dislikes=[dislike])]
    assert not [movie["title"] for movie in recommender.rank(rows(vetoed), limit=len(graph.movies)) if in_family(movie)]


def test_random_groups_match_the_reference_rules_on_the_big_catalogue(big):
    graph, recommender, truth = big
    with_results = 0
    for members in random_groups(graph, seed=99, count=24):
        expected = reference.rank(truth, members)
        actual = recommender.rank(rows(members))
        assert [(movie["id"], movie["score"]) for movie in actual] == [(movie["id"], movie["score"]) for movie in expected]
        for movie in actual:
            for member, match in zip(members, movie["matches"]):
                links = sorted(taste for taste in member["likes"] if truth.liked(taste, movie["id"]))
                assert links and match["because"] == [graph.entities[taste]["label"] for taste in links]
                assert not any(truth.disliked(taste, movie["id"]) for other in members for taste in other["dislikes"])
        with_results += bool(actual)
    assert with_results >= 8
