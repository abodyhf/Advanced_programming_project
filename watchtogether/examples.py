"""Example groups with hand-checked expected shortlists (starter catalogue).

Used by the tests and by `python -m watchtogether.examples`, which prints what the
recommender returns for each group so the results can be pasted into a report.
"""
import argparse
import json
from pathlib import Path
from .graph import GraphStore, ROOT
from .recommender import Recommender

EXAMPLES = [
    {
        "name": "shared tastes",
        "story": "Three friends who all like Wes Anderson, comedy and adventure.",
        "members": [
            {"nickname": "Ana", "likes": ["person:wes-anderson", "genre:comedy", "genre:adventure"], "dislikes": []},
            {"nickname": "Ben", "likes": ["person:wes-anderson", "genre:comedy", "genre:adventure"], "dislikes": []},
            {"nickname": "Cem", "likes": ["person:wes-anderson", "genre:comedy", "genre:adventure"], "dislikes": []},
        ],
        # Every Wes Anderson comedy-adventure hits all four weighted points for everyone.
        "expected": ["Fantastic Mr. Fox", "Isle of Dogs", "Moonrise Kingdom",
                     "The Grand Budapest Hotel", "The Life Aquatic with Steve Zissou"],
        "expected_scores": [100.0, 100.0, 100.0, 100.0, 100.0],
    },
    {
        "name": "conflicting tastes",
        "story": "Ana loves horror and Jordan Peele; Ben wants comedy or mystery and hates horror.",
        "members": [
            {"nickname": "Ana", "likes": ["genre:horror", "genre:thriller", "person:jordan-peele"], "dislikes": []},
            {"nickname": "Ben", "likes": ["genre:comedy", "genre:mystery"], "dislikes": ["genre:horror"]},
        ],
        # Get Out would score highest (60) but Ben's horror dislike vetoes it. What is left
        # only reaches Ana through "thriller" (1 of her 4 weighted points).
        "expected": ["Gone Girl", "Ocean’s Eleven", "Parasite", "The Prestige"],
        "expected_scores": [30.0, 30.0, 30.0, 30.0],
        "vetoed": ["Get Out", "Us", "What We Do in the Shadows"],
    },
    {
        "name": "balanced beats one-sided",
        "story": "Ana likes animation adventures, Ben likes romantic dramas; comedy is the bridge.",
        "members": [
            {"nickname": "Ana", "likes": ["genre:comedy", "genre:adventure", "genre:animation"], "dislikes": []},
            {"nickname": "Ben", "likes": ["genre:comedy", "genre:drama", "genre:romance"], "dislikes": []},
        ],
        # Toy Story is perfect for Ana but weak for Ben (score 46.67); films covering two of
        # three likes for both (66.67) rank above it.
        "expected": ["Hunt for the Wilderpeople", "Inside Out", "Little Miss Sunshine",
                     "Moonrise Kingdom", "The Grand Budapest Hotel"],
        "expected_scores": [66.6667] * 5,
        "below": ["Toy Story", "Forrest Gump"],
    },
    {
        "name": "no common movie",
        "story": "Ana only likes anime, family films and Miyazaki; Ben only likes horror, thrillers and Jordan Peele.",
        "members": [
            {"nickname": "Ana", "likes": ["genre:anime", "genre:family", "person:hayao-miyazaki"], "dislikes": []},
            {"nickname": "Ben", "likes": ["genre:horror", "genre:thriller", "person:jordan-peele"], "dislikes": []},
        ],
        "expected": [],
        "expected_scores": [],
    },
    {
        "name": "liked film",
        "story": "Ana names Inception as a favourite; Ben likes Christopher Nolan. Both like war and music films.",
        "members": [
            {"nickname": "Ana", "likes": ["film:inception-2010", "genre:war", "genre:music"], "dislikes": []},
            {"nickname": "Ben", "likes": ["person:christopher-nolan", "genre:war", "genre:music"], "dislikes": []},
        ],
        # Nolan films reach Ana through Inception (1 of 3 points) and Ben through Nolan (2 of 4):
        # 100 x (0.6 x 1/3 + 0.4 x (1/3 + 1/2) / 2) = 36.67. Jojo Rabbit only shares "war": 26.67.
        "expected": ["Inception", "Interstellar", "The Dark Knight", "The Prestige", "Jojo Rabbit"],
        "expected_scores": [36.6667] * 4 + [26.6667],
        "expected_reasons": {"Inception": "this film",
                             "Interstellar": "same director: Christopher Nolan; shared genre: Science fiction",
                             "The Dark Knight": "same director: Christopher Nolan; shared genre: Action",
                             "The Prestige": "same director: Christopher Nolan; shared genre: Thriller"},
    },
]


def as_rows(members):
    """Shape example members like the SQLite rows the recommender receives."""
    return [{"id": f"example-{index}", "nickname": member["nickname"],
             "likes": json.dumps(member["likes"]), "dislikes": json.dumps(member["dislikes"])}
            for index, member in enumerate(members)]


def run(graph=None):
    graph = graph or GraphStore(ROOT / "data/catalog.json")
    recommender = Recommender(graph)
    return [(example, recommender.rank(as_rows(example["members"]))) for example in EXAMPLES]


def report(results):
    lines = ["# Recommendation examples", "",
             "Generated by `python -m watchtogether.examples --write` on the 80-film starter catalogue.", ""]
    for example, movies in results:
        titles = [movie["title"] for movie in movies]
        status = "as expected" if titles == example["expected"] else "UNEXPECTED"
        lines += [f"## {example['name'].capitalize()} ({status})", "", example["story"], ""]
        for member in example["members"]:
            dislikes = ", ".join(member["dislikes"]) or "nothing"
            lines.append(f"- {member['nickname']} likes {', '.join(member['likes'])}; dislikes {dislikes}")
        lines.append("")
        if not movies:
            lines += ["No film matches everyone, so the app asks the group to change tastes.", ""]
            continue
        lines += ["| # | Film | Score | Why, per member |", "| --- | --- | --- | --- |"]
        for number, movie in enumerate(movies, 1):
            why = "; ".join(f"{match['nickname']} {match['match']}%: {connections(match)}" for match in movie["matches"])
            lines.append(f"| {number} | {movie['title']} ({movie['year']}) | {movie['score']} | {why} |")
        lines.append("")
    return "\n".join(lines)


def connections(match):
    """Each like and how it reaches the film, as the shortlist card shows it."""
    return ", ".join(reason["label"] + (f" ({reason['why']})" if reason["why"] != "genre" else "")
                     for reason in match["reasons"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write docs/EXAMPLES.md")
    args = parser.parse_args()
    text = report(run())
    if args.write:
        Path(ROOT / "docs/EXAMPLES.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
