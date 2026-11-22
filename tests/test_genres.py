"""Genre hierarchy: imported Wikidata genres name their parent inside the label."""
import json
import pytest
from watchtogether.graph import GraphStore, genre_parents
from watchtogether.recommender import Recommender


def test_compound_names_become_subgenres():
    parents = genre_parents(["comedy", "horror", "comedy-horror", "science-fiction", "science-fiction-horror",
                             "western", "spaghetti-western", "drama", "romance", "romantic-drama"])
    assert set(parents["comedy-horror"]) == {"comedy", "horror"}
    assert set(parents["science-fiction-horror"]) == {"science-fiction", "horror"}
    assert parents["spaghetti-western"] == ["western"]
    assert set(parents["romantic-drama"]) == {"romance", "drama"}


def test_known_kinds_without_the_word_in_their_name():
    parents = genre_parents(["horror", "slasher", "zombie", "science-fiction", "cyberpunk", "thriller", "suspense"])
    assert parents["slasher"] == ["horror"] and parents["zombie"] == ["horror"]
    assert parents["cyberpunk"] == ["science-fiction"] and parents["suspense"] == ["thriller"]


def test_words_that_are_not_the_genre_are_left_alone():
    parents = genre_parents(["action", "animated", "live-action-animated", "fiction", "science-fiction",
                             "documentary", "pseudo-documentary"])
    assert parents.get("live-action-animated") == ["animated"]  # live action is not an action film
    assert "science-fiction" not in parents  # a sci-fi film is not tagged with the vague "fiction"
    assert "pseudo-documentary" not in parents  # staged fiction, not a documentary


def test_only_genres_in_the_catalogue_get_parents():
    parents = genre_parents(["comedy", "drama"])
    assert parents == {}  # starter-only entries such as anime -> animation stay out


def film(number, genres):
    return {"id": f"film:test-{number}", "title": f"Test {number}", "year": 2000 + number, "genres": genres,
            "directors": [f"Director {number}"], "cast": [f"Actor {number}"]}


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    films = [film(1, ["comedy"]), film(2, ["comedy-horror"]), film(3, ["slasher", "comedy"]),
             film(4, ["zombie-comedy"]), film(5, ["horror"]), film(6, ["spaghetti-western"]),
             film(7, ["black-comedy", "drama"]), film(8, ["western"])]
    path = tmp_path_factory.mktemp("genres") / "catalogue.json"
    path.write_text(json.dumps({"source": "test", "films": films}))
    return Recommender(GraphStore(path))


def member(name, likes, dislikes=()):
    return {"id": name, "nickname": name, "likes": json.dumps(likes), "dislikes": json.dumps(list(dislikes))}


def test_dislike_of_horror_removes_every_kind_of_horror(small):
    ranked = small.rank([member("A", ["genre:comedy"]), member("B", ["genre:comedy"], ["genre:horror"])], limit=50)
    assert [movie["title"] for movie in ranked] == ["Test 1", "Test 7"]


def test_like_reaches_compound_subgenres(small):
    ranked = small.rank([member("A", ["genre:comedy"]), member("B", ["genre:comedy"])], limit=50)
    assert {movie["title"] for movie in ranked} == {"Test 1", "Test 2", "Test 3", "Test 4", "Test 7"}
    western = small.rank([member("A", ["genre:western"]), member("B", ["genre:western"])], limit=50)
    assert [movie["title"] for movie in western] == ["Test 6", "Test 8"]


def test_genre_audit_counts_what_the_old_tree_let_through():
    from watchtogether.genre_audit import audit
    films = [film(1, ["horror"]), film(2, ["slasher"]), film(3, ["comedy-horror"]), film(4, ["comedy"])]
    [horror] = audit(films, ["horror"])
    assert horror == {"dislike": "horror", "tagged": 1, "excluded_before": 1, "excluded_now": 3, "leaked_before": 2}
