"""Independent, slow-but-obvious version of the recommendation rules in README.md.

It reads the catalogue JSON directly and never touches RDF or SPARQL, so the tests can
compare it with the real recommender and catch query or scoring mistakes.
"""
import json
from watchtogether.graph import slug


def load(catalog_path, genre_parents):
    payload = json.loads(open(catalog_path, encoding="utf-8").read())
    return Catalogue(payload["films"], genre_parents)


class Catalogue:
    def __init__(self, films, genre_parents):
        self.films = {film["id"]: film for film in films}
        self.parents = {child: set(parents) for child, parents in genre_parents.items()}
        self.labels = {}
        self.people = {}
        for film_id, film in self.films.items():
            self.labels[film_id] = film["title"]
            directors = self._ids(film, "directors")
            cast = self._ids(film, "cast")
            self.people[film_id] = {"directors": directors, "cast": cast}
            for genre in film["genres"]:
                self.labels.setdefault("genre:" + genre, genre)
            for field in ("directors", "cast"):
                for person_id, name in zip(self._ids(film, field), film[field]):
                    self.labels.setdefault(person_id, name)

    @staticmethod
    def _ids(film, field):
        imported = film.get(field + "_ids")
        return list(imported) if imported else ["person:" + slug(name) for name in film[field]]

    def ancestors(self, genre):
        seen, todo = {genre}, [genre]
        while todo:
            for parent in self.parents.get(todo.pop(), ()):
                if parent not in seen:
                    seen.add(parent)
                    todo.append(parent)
        return seen

    def genre_closure(self, film_id):
        return {"genre:" + g for genre in self.films[film_id]["genres"] for g in self.ancestors(genre)}

    def everyone(self, film_id):
        return set(self.people[film_id]["directors"]) | set(self.people[film_id]["cast"])

    def liked(self, taste, film_id):
        """True when a liked entity connects to the film."""
        if taste.startswith("genre:"):
            return taste in self.genre_closure(film_id)
        if taste in self.films:
            if taste == film_id:
                return True
            return bool(self.genre_closure(taste) & self.genre_closure(film_id)
                        or set(self.people[taste]["directors"]) & set(self.people[film_id]["directors"])
                        or set(self.people[taste]["cast"]) & set(self.people[film_id]["cast"]))
        return taste in self.everyone(film_id)

    def disliked(self, taste, film_id):
        """True when a disliked entity rules the film out."""
        if taste.startswith("genre:"):
            return taste in self.genre_closure(film_id)
        if taste in self.films:
            return taste == film_id
        return taste in self.everyone(film_id)


def weight(taste):
    return 2 if taste.startswith("person:") else 1


def rank(catalogue, members, limit=5):
    """members: list of dicts with id, nickname, likes and dislikes (Python lists)."""
    results = []
    for film_id, film in catalogue.films.items():
        if any(catalogue.disliked(taste, film_id) for member in members for taste in member["dislikes"]):
            continue
        scores, matches = [], []
        for member in members:
            links = sorted(taste for taste in member["likes"] if catalogue.liked(taste, film_id))
            if not links:
                break
            score = sum(map(weight, links)) / sum(map(weight, member["likes"]))
            scores.append(score)
            matches.append({"member_id": member["id"], "nickname": member["nickname"],
                            "match": round(100 * score), "links": links})
        else:
            group = round(100 * (0.6 * min(scores) + 0.4 * sum(scores) / len(scores)), 4)
            results.append({"id": film_id, "title": film["title"], "score": group, "matches": matches})
    results.sort(key=lambda movie: (-movie["score"], movie["title"].casefold(), movie["id"]))
    return results[:limit]
