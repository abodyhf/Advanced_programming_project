"""How many films a genre dislike removes, with the original and the current genre tree.

    python -m watchtogether.genre_audit                 # data/wikidata.json if present
    python -m watchtogether.genre_audit --catalog data/catalog.json

Works on the catalogue JSON alone (no graph build), so it runs in about a second.
"""
import argparse
import json
from pathlib import Path
from .graph import ROOT, genre_parents

# The hand-written table before compound Wikidata genres were linked to their parents.
ORIGINAL_PARENTS = {"anime": ["animation"], "heist": ["crime"], "romantic-comedy": ["romance", "comedy"],
                    "psychological-thriller": ["thriller"], "superhero": ["action", "science-fiction"]}
DISLIKES = ["horror", "comedy", "romance", "western", "war", "science-fiction", "documentary", "musical",
            "thriller", "crime", "action", "fantasy", "drama", "pornographic"]


def closure(genre, parents):
    seen, todo = {genre}, [genre]
    while todo:
        for parent in parents.get(todo.pop(), []):
            if parent not in seen:
                seen.add(parent)
                todo.append(parent)
    return seen


def audit(films, dislikes=DISLIKES):
    now = genre_parents({genre for film in films for genre in film["genres"]})
    rows = []
    for dislike in dislikes:
        tagged = sum(dislike in film["genres"] for film in films)
        before = sum(any(dislike in closure(genre, ORIGINAL_PARENTS) for genre in film["genres"]) for film in films)
        after = sum(any(dislike in closure(genre, now) for genre in film["genres"]) for film in films)
        rows.append({"dislike": dislike, "tagged": tagged, "excluded_before": before, "excluded_now": after,
                     "leaked_before": after - before})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    default = ROOT / "data/wikidata.json"
    parser.add_argument("--catalog", type=Path, default=default if default.exists() else ROOT / "data/catalog.json")
    args = parser.parse_args(argv)
    films = json.loads(args.catalog.read_text(encoding="utf-8"))["films"]
    rows = audit(films)
    print(f"{len(films)} films in {args.catalog.name}\n")
    print("| Disliked genre | Films tagged with it | Removed before | Removed now | Got through before |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for row in rows:
        print(f"| {row['dislike']} | {row['tagged']} | {row['excluded_before']} | {row['excluded_now']} | {row['leaked_before']} |")
    return rows


if __name__ == "__main__":
    main()
