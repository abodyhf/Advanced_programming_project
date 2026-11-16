"""Fairness score: 60% weakest member's match + 40% group average."""
import json

class Recommender:
    def __init__(self, graph):
        self.graph = graph

    def rank(self, members, limit=5):
        members = [dict(member) for member in members]
        profiles = []
        excluded = set()
        for member in members:
            likes = json.loads(member["likes"])
            dislikes = json.loads(member["dislikes"])
            matched = self.graph.links_for(likes)
            excluded.update(self.graph.links_for(dislikes, expand_films=False))
            profiles.append((member, likes, matched))
        recommendations = []
        for film_id, film in self.graph.movies.items():
            if film_id in excluded:
                continue
            scores, explanations = [], []
            for member, likes, matched in profiles:
                links = matched.get(film_id, set())
                if not links:
                    break
                weight = lambda item: 2 if item.startswith("person:") else 1
                score = sum(weight(item) for item in links) / sum(weight(item) for item in likes)
                scores.append(score)
                explanations.append({"member_id": member["id"], "nickname": member["nickname"],
                                     "match": round(100 * score),
                                     "because": [self.graph.entities[item]["label"] for item in sorted(links)]})
            else:
                score = round(100 * (0.6 * min(scores) + 0.4 * sum(scores) / len(scores)), 4)
                recommendations.append({**film, "score": score, "matches": explanations})
        recommendations.sort(key=lambda movie: (-movie["score"], movie["title"].casefold(), movie["id"]))
        return recommendations[:limit]
