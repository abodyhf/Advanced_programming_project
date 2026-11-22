"""Repeatable recommendation timing for groups of 2, 4 and 8 people.

    python -m watchtogether.benchmark                      # starter + imported catalogue
    python -m watchtogether.benchmark --repeats 20 --out docs/performance/after.json

Group profiles are generated from a fixed seed and the catalogue contents only, so the
same command measures the same groups before and after a code change. Each measurement
is repeated after a warm-up run; the JSON keeps every raw sample.
"""
import argparse
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from .graph import ROOT

try:
    import resource  # not available on Windows
except ImportError:
    resource = None

SIZES = (2, 4, 8)


def popular(graph):
    """Genres and people ordered by how many films they appear in (ties by id)."""
    counts = Counter()
    for film_id, film in graph.movies.items():
        counts.update("genre:" + genre for genre in film["genres"])
        for field in ("directors", "cast"):
            ids = film.get(field + "_ids") or []
            counts.update(ids)
    by_count = lambda key: (-counts[key], key)
    genres = sorted((key for key in graph.entities if graph.entities[key]["kind"] == "genre" and counts[key]), key=by_count)
    people = sorted((key for key in graph.entities if graph.entities[key]["kind"] == "person"), key=by_count)
    if not counts.get(people[0]):  # starter catalogue: no imported ids, count by name instead
        names = Counter(name for film in graph.movies.values() for field in ("directors", "cast") for name in film[field])
        people = sorted(people, key=lambda key: (-names[graph.entities[key]["label"]], key))
    return genres, people


def scenarios(graph, size, seed):
    """Two deterministic groups of `size` people: identical tastes, and mixed tastes."""
    genres, people = popular(graph)
    films = sorted(graph.movies)
    rng = random.Random(f"{seed}-{size}")
    shared = {"likes": [genres[1], genres[0], people[0]], "dislikes": [genres[6]]}
    mixed = []
    for _ in range(size):
        likes = rng.sample(genres[:12], 2) + rng.sample(people[:40], 1) + rng.sample(films, 1)
        dislikes = [rng.choice([genre for genre in genres[:30] if genre not in likes])]
        mixed.append({"likes": likes, "dislikes": dislikes})
    return {"shared": [shared] * size, "mixed": mixed}


def rows(profiles):
    return [{"id": f"bench-{index}", "nickname": f"Bench {index}", "likes": json.dumps(profile["likes"]),
             "dislikes": json.dumps(profile["dislikes"])} for index, profile in enumerate(profiles)]


def summary(samples):
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {"median_ms": round(statistics.median(ordered), 2), "p95_ms": round(p95, 2),
            "min_ms": round(ordered[0], 2), "max_ms": round(ordered[-1], 2),
            "samples_ms": [round(value, 2) for value in samples]}


def timed(function, repeats, warmup=1, prepare=None):
    """Run `function` warmup + repeats times; `prepare` runs untimed before each call."""
    samples = []
    for number in range(warmup + repeats):
        if prepare:
            prepare()
        started = time.perf_counter()
        function()
        if number >= warmup:
            samples.append(1000 * (time.perf_counter() - started))
    return samples


def api_round(client, graph, profiles):
    """Create a ready group through the API; return (reset, recommend) callables."""
    headers = []
    owner = client.post("/api/groups", json={"title": "Benchmark", "nickname": "Bench 0"}).json()
    group_id = owner["group_id"]
    people = [owner] + [client.post(f"/api/groups/{group_id}/members", json={"nickname": f"Bench {index}"}).json()
                        for index in range(1, len(profiles))]
    for person, profile in zip(people, profiles):
        headers.append({"Authorization": "Bearer " + person["token"]})
        saved = client.put(f"/api/groups/{group_id}/profile", headers=headers[-1], json=profile)
        saved.raise_for_status()

    def reset():
        client.post(f"/api/groups/{group_id}/reset", headers=headers[0]).raise_for_status()

    def recommend():
        response = client.post(f"/api/groups/{group_id}/recommendations", headers=headers[0])
        if response.status_code not in (200, 409):  # 409: no film suits everyone
            response.raise_for_status()
    return reset, recommend


def measure(catalog, repeats, seed):
    from fastapi.testclient import TestClient
    from .api import create_app
    with tempfile.TemporaryDirectory() as data_dir:
        started = time.perf_counter()
        app = create_app(data_dir, catalog_path=catalog)
        startup = time.perf_counter() - started
        graph, recommender = app.state.graph, app.state.recommender
        result = {"catalog": str(Path(catalog).relative_to(ROOT)) if Path(catalog).is_relative_to(ROOT) else str(catalog),
                  "films": len(graph.movies), "entities": len(graph.entities),
                  "startup_s": round(startup, 2), "groups": []}
        with TestClient(app) as client:
            for size in SIZES:
                for name, profiles in scenarios(graph, size, seed).items():
                    ranked = recommender.rank(rows(profiles))
                    reset, recommend = api_round(client, graph, profiles)
                    entry = {"members": size, "scenario": name, "profiles": profiles,
                             "results": len(ranked), "top": [movie["title"] for movie in ranked],
                             "rank": summary(timed(lambda: recommender.rank(rows(profiles)), repeats)),
                             "api": summary(timed(recommend, repeats, prepare=reset))}
                    result["groups"].append(entry)
                    print(f"  {result['catalog']:<22} {size} members {name:<6} rank median {entry['rank']['median_ms']:>9.2f} ms"
                          f"  api median {entry['api']['median_ms']:>9.2f} ms  ({len(ranked)} films)", flush=True)
        if resource:  # Linux reports kilobytes
            result["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    return result


def environment():
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    except OSError:
        commit, dirty = "unknown", False
    return {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": commit + ("+dirty" if dirty else ""),
            "python": platform.python_version(), "platform": platform.platform(), "cpu": platform.processor() or platform.machine(),
            "cpu_count": os.cpu_count()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", action="append", help="catalogue JSON (repeatable); default: starter and data/wikidata.json")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, help="write the raw results as JSON")
    args = parser.parse_args(argv)
    catalogs = args.catalog or [str(ROOT / "data/catalog.json")] + ([str(ROOT / "data/wikidata.json")] if (ROOT / "data/wikidata.json").exists() else [])
    report = {"environment": environment(), "repeats": args.repeats, "seed": args.seed, "catalogs": []}
    for catalog in catalogs:
        # Each catalogue is measured in a fresh process so startup and memory are not shared.
        if len(catalogs) > 1:
            with tempfile.NamedTemporaryFile("r", suffix=".json") as part:
                subprocess.run([sys.executable, "-m", "watchtogether.benchmark", "--catalog", catalog, "--repeats", str(args.repeats),
                                "--seed", str(args.seed), "--out", part.name], cwd=ROOT, check=True)
                report["catalogs"] += json.loads(Path(part.name).read_text())["catalogs"]
        else:
            report["catalogs"].append(measure(catalog, args.repeats, args.seed))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
