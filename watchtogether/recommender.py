"""Fairness score: 60% weakest member's match + 40% group average."""
import heapq
import json


def weight(taste):
    """People say more about taste than a genre or a single film."""
    return 2 if taste.startswith("person:") else 1


class Recommender:
    def __init__(self, graph):
        self.graph = graph

    def rank(self, members, limit=5, *, allow_compromise=False, eligible=None):
        profiles = []
        for member in members:
            likes = json.loads(member["likes"])
            profiles.append((dict(member), set(likes), sum(map(weight, likes)), json.loads(member["dislikes"])))
        # One query for every like in the group and one for every dislike, instead of two per member.
        group_likes = sorted(set().union(*(likes for _, likes, _, _ in profiles)))
        group_dislikes = sorted({taste for *_, dislikes in profiles for taste in dislikes})
        matched = self.graph.links_for(group_likes)
        excluded = self.graph.links_for(group_dislikes, expand_films=False)
        scored = []
        for film_id, tastes in matched.items():
            if film_id in excluded or (eligible is not None and film_id not in eligible):
                continue
            scores = []
            for _, likes, total, _ in profiles:
                links = tastes & likes
                if not links and not allow_compromise:
                    break  # every member needs at least one like that reaches the film
                scores.append(sum(map(weight, links)) / total)
            else:
                coverage = sum(score > 0 for score in scores) if allow_compromise else len(profiles)
                score = round(100 * (0.6 * min(scores) + 0.4 * sum(scores) / len(scores)), 4)
                scored.append((-coverage, -score, self.graph.movies[film_id]["title"].casefold(), film_id))
        # If profiles changed since the first attempt, prefer a regular ballot when possible.
        if allow_compromise and any(candidate[0] == -len(profiles) for candidate in scored):
            scored = [candidate for candidate in scored if candidate[0] == -len(profiles)]
        recommendations = []
        for _, negative_score, _, film_id in heapq.nsmallest(limit, scored):
            explanations = []
            for member, likes, total, _ in profiles:
                links = sorted(matched[film_id] & likes)
                explanations.append({"member_id": member["id"], "nickname": member["nickname"],
                                     "match": round(100 * (sum(map(weight, links)) / total)),
                                     "because": [self.graph.entities[item]["label"] for item in links],
                                     "reasons": [{"id": item, "label": self.graph.entities[item]["label"],
                                                  "why": self.graph.why(item, film_id)} for item in links]})
            recommendations.append({**self.graph.movies[film_id], "score": -negative_score, "matches": explanations})
        return recommendations
