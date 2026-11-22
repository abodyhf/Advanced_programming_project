"""Explanations must say why a film reached each member, and every reason must be true."""
import pytest
from watchtogether.graph import GraphStore, ROOT, label_genre
from watchtogether.recommender import Recommender
from test_recommendations import random_groups, rows
from conftest import auth, make_group, start


@pytest.fixture(scope="module")
def graph():
    return GraphStore(ROOT / "data/catalog.json")


@pytest.fixture(scope="module")
def recommender(graph):
    return Recommender(graph)


def reasons_for(recommender, likes_by_member, title):
    members = [{"id": str(index), "nickname": f"M{index}", "likes": likes, "dislikes": []}
               for index, likes in enumerate(likes_by_member)]
    movie = next(movie for movie in recommender.rank(rows(members), limit=100) if movie["title"] == title)
    return [{reason["label"]: reason["why"] for reason in match["reasons"]} for match in movie["matches"]]


def test_liked_film_names_what_it_shares(recommender):
    first, second = reasons_for(recommender, [["film:inception-2010"], ["person:christopher-nolan"]], "The Prestige")
    assert first == {"Inception": "same director: Christopher Nolan; shared genre: Thriller"}
    assert second == {"Christopher Nolan": "directs it"}


def test_liked_film_on_the_shortlist_is_itself(recommender):
    first, _ = reasons_for(recommender, [["film:inception-2010"], ["genre:action"]], "Inception")
    assert first == {"Inception": "this film"}


def test_genre_reason_names_the_subgenre_when_that_is_the_link(recommender):
    first, second = reasons_for(recommender, [["genre:thriller"], ["genre:mystery"]], "Gone Girl")
    assert first == {"Thriller": "via Psychological Thriller"}
    assert second == {"Mystery": "genre"}


def test_person_reason_says_cast_or_director(recommender):
    reasons = reasons_for(recommender, [["person:tom-hanks"], ["genre:animation"]], "Toy Story")
    assert reasons[0] == {"Tom Hanks": "in the cast"}
    both = reasons_for(recommender, [["person:taika-waititi"], ["genre:horror"]], "What We Do in the Shadows")
    assert both[0] == {"Taika Waititi": "directs it and is in the cast"}


def check_reason(graph, film, taste, why):
    """True only if the sentence describes a real link between the liked taste and the film."""
    entity, record = graph.entities[taste], graph.movies[film]
    if taste == film:
        return why == "this film"
    if entity["kind"] == "genre":
        genre = taste[6:]
        if genre in record["genres"]:
            return why == "genre"
        named = why.removeprefix("via ").split(", ")
        tagged = {label_genre(tag): tag for tag in record["genres"]}
        return why.startswith("via ") and all(label in tagged and genre in graph.ancestors(tagged[label]) for label in named)
    if entity["kind"] == "person":
        directs, acts = entity["label"] in record["directors"], entity["label"] in record["cast"]
        return why == {(True, False): "directs it", (False, True): "in the cast",
                       (True, True): "directs it and is in the cast"}.get((directs, acts))
    liked = graph.movies[taste]
    for part in why.split("; "):
        heading, names = part.split(": ", 1)
        names = names.split(", ")
        if heading == "same director":
            ok = all(name in liked["directors"] and name in record["directors"] for name in names)
        elif heading == "shared cast":
            ok = all(name in liked["cast"] and name in record["cast"] for name in names)
        elif heading == "shared genre":
            shared = {label_genre(genre) for genre in set(graph.film_genres(taste)) & set(graph.film_genres(film))}
            ok = all(name in shared for name in names)
        else:
            ok = False
        if not ok:
            return False
    return bool(why)


def test_every_reason_on_random_shortlists_is_true(graph, recommender):
    checked = 0
    for members in random_groups(graph, seed=5, count=60):
        for movie in recommender.rank(rows(members)):
            for match in movie["matches"]:
                assert [reason["label"] for reason in match["reasons"]] == match["because"]
                for reason in match["reasons"]:
                    assert check_reason(graph, movie["id"], reason["id"], reason["why"]), (movie["title"], reason)
                    checked += 1
    assert checked > 150


def test_reasons_reach_the_browser(client):
    gid, people = make_group(client, likes=["film:inception-2010", "genre:drama", "person:tom-hanks"])
    movie = start(client, gid, people)[0]
    assert all(match["reasons"] and all(reason["why"] for reason in match["reasons"]) for match in movie["matches"])
