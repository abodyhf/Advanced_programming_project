import json
from watchtogether import benchmark
from watchtogether.graph import ROOT


def test_benchmark_measures_two_four_and_eight_members(tmp_path):
    out = tmp_path / "bench.json"
    benchmark.main(["--catalog", str(ROOT / "data/catalog.json"), "--repeats", "2", "--out", str(out)])
    report = json.loads(out.read_text())
    [catalog] = report["catalogs"]
    assert catalog["films"] == 80 and catalog["startup_s"] > 0
    assert [(group["members"], group["scenario"]) for group in catalog["groups"]] == [
        (size, name) for size in (2, 4, 8) for name in ("shared", "mixed")]
    for group in catalog["groups"]:
        assert len(group["profiles"]) == group["members"]
        assert len(group["rank"]["samples_ms"]) == len(group["api"]["samples_ms"]) == 2
        assert group["rank"]["min_ms"] <= group["rank"]["median_ms"] <= group["rank"]["max_ms"]


def test_benchmark_groups_are_the_same_every_run():
    from watchtogether.graph import GraphStore
    graph = GraphStore(ROOT / "data/catalog.json")
    assert benchmark.scenarios(graph, 4, 2026) == benchmark.scenarios(graph, 4, 2026)
    assert benchmark.scenarios(graph, 4, 2026) != benchmark.scenarios(graph, 4, 1)
