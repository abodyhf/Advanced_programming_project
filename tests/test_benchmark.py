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


def test_compare_prints_one_row_per_measured_group():
    saved = ROOT / "docs/performance/baseline.json"
    table = benchmark.compare(saved, saved)
    groups = sum(len(catalog["groups"]) for catalog in json.loads(saved.read_text())["catalogs"])
    assert table.count("1.0x") == 2 * groups  # rank and API, identical runs


def test_summary_has_a_row_per_run():
    runs = [ROOT / "docs/performance/baseline.json", ROOT / "docs/performance/after.json"]
    lines = benchmark.summarise(runs).splitlines()
    assert len(lines) == 4 and lines[2].startswith("| baseline (850de32) |") and lines[3].startswith("| after (")
