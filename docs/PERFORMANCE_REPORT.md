# Performance report

Date: 22 November 2026. Machine: Linux 6.1, Python 3.11.2, 6 CPU cores shared with other jobs (load average 2-3 during the runs), ordinary disk where one SQLite commit with fsync took about 19 ms. Absolute times will differ on other machines; compare the before/after ratios.

## What is measured

`python -m watchtogether.benchmark` builds the app the normal way (`create_app`) and times recommendations for groups of **2, 4 and 8 members** on both catalogues: the 80-film starter catalogue and the **10,000-film Wikidata catalogue** (`data/wikidata.json`, imported by Member 1).

For each group size there are two groups, generated from the catalogue contents with a fixed seed (2026), so every run measures the same people:

- **shared**: everyone likes the two most common genres and the most frequent person, and dislikes the 7th most common genre (on 10k films: drama, comedy, one prolific actor; dislike horror).
- **mixed**: each member likes 2 of the 12 most common genres, 1 of the 40 most frequent people and 1 random film, and dislikes 1 of the 30 most common genres.

Timings:

- **rank**: `Recommender.rank()` for the group, in process.
- **API**: `POST /api/groups/{id}/recommendations` through FastAPI, including the SQLite transaction that saves the shortlist (the round is reset, untimed, before each call).
- **startup**: `create_app()` (catalogue load, RDF graph, SHACL check, query index), and peak memory of the process.

Each measurement has one warm-up call and then 10 timed calls (5 for the per-commit runs). Tables show medians; every raw sample, the group profiles, the commit and the machine details are in the JSON files under `docs/performance/`.

Reproduce:

```bash
python -m watchtogether.benchmark --repeats 10 --out docs/performance/after.json
python -m watchtogether.benchmark --compare docs/performance/baseline.json docs/performance/after.json

# the "before" numbers: same command on the commit before any change
git worktree add ../baseline b7fbbe6
cd ../baseline && python -m watchtogether.benchmark --repeats 10 --out ../before.json
```

## Result

Before: commit b7fbbe6 (original code plus the benchmark), after: commit 360d256. Medians in ms, 10 timed runs each.

| Catalogue | Members | Group | Rank before | Rank after | Speed-up | API before | API after | Speed-up |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 80 films | 2 | shared | 10.9 | 2.1 | 5.2x | 116.6 | 14.3 | 8.2x |
| 80 films | 2 | mixed | 10.8 | 3.8 | 2.8x | 127.2 | 16.3 | 7.8x |
| 80 films | 4 | shared | 22.1 | 2.5 | 8.8x | 144.5 | 16.0 | 9.0x |
| 80 films | 4 | mixed | 23.7 | 5.8 | 4.1x | 240.9 | 20.0 | 12.1x |
| 80 films | 8 | shared | 41.6 | 3.4 | 12.2x | 418.9 | 20.7 | 20.2x |
| 80 films | 8 | mixed | 45.5 | 5.5 | 8.3x | 59.4 | 16.9 | 3.5x |
| **10,000 films** | 2 | shared | 415.7 | 117.6 | 3.5x | 1306.1 | 135.3 | 9.7x |
| **10,000 films** | 2 | mixed | 442.7 | 44.1 | 10.0x | 1042.4 | 98.7 | 10.6x |
| **10,000 films** | 4 | shared | 899.8 | 94.3 | 9.5x | 1839.3 | 153.8 | 12.0x |
| **10,000 films** | 4 | mixed | 889.8 | 100.2 | 8.9x | 1814.5 | 191.6 | 9.5x |
| **10,000 films** | 8 | shared | 1771.0 | 88.1 | 20.1x | 2667.2 | 130.9 | 20.4x |
| **10,000 films** | 8 | mixed | 1637.5 | 149.5 | 11.0x | 2523.8 | 243.3 | 10.4x |

| Catalogue | Startup before | Startup after | Peak memory before | Peak memory after |
| --- | ---: | ---: | ---: | ---: |
| 80 films | 2.63 s | 1.35 s | 81 MB | 79 MB |
| 10,000 films | 45.1 s | 25.2 s | 912 MB | 958 MB |

The slowest single API call on 10,000 films went from 4.7 s to 0.5 s. Before the change, cost grew linearly with group size (about 0.22 s per member). Now it depends on how many different tastes the group has, not on head count: 8 people with the same tastes cost no more than 2 (88 vs 118 ms). (The 8-mixed group on the starter catalogue has no common film, so its API call returns "no match" without writing; that is why its "before" is small.)

The shortlists are the same before and after, except where the genre fix below changes which films count as comedy, horror and so on. The reference tests (`tests/test_recommendations.py`, `tests/test_big_catalogue.py`) prove the faster code returns exactly what the plain rule-by-rule implementation returns.

## Where the time went, and each fix

`docs/performance/steps/` has a 10k-film run (5 timed calls) at each commit of the series, so every step can be checked on its own:

```bash
python -m watchtogether.benchmark --summary docs/performance/baseline.json docs/performance/steps/{9060954,769fc80,d4054c9,d6a4f6f,50ae9fd,f7f6573,9950549,157328d,d24c6f8}.json docs/performance/after.json
```

| Step (commit) | Startup s | Rank 2 shared / mixed | Rank 4 shared / mixed | Rank 8 shared / mixed | API 8 shared / mixed | Slowest API call |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline (b7fbbe6) | 45.1 | 416 / 443 | 900 / 890 | 1771 / 1637 | 2667 / 2524 | 4706 |
| 1. genre tree fix (9060954) | 43.6 | 494 / 473 | 978 / 1458 | 2076 / 1774 | 3993 / 2669 | 5005 |
| 2. genre closure stored, new query shape (769fc80) | 45.3 | 250 / 238 | 642 / 270 | 633 / 398 | 2553 / 1328 | 3032 |
| 3. one query per group (d4054c9) | 50.2 | 145 / 131 | 129 / 252 | 199 / 327 | 545 / 1064 | 1639 |
| 4. rows read as tuples (d6a4f6f) | 46.3 | 111 / 88 | 108 / 141 | 118 / 288 | 910 / 1288 | 1728 |
| 5. each genre/person read once (50ae9fd) | 50.9 | 121 / 83 | 102 / 149 | 127 / 203 | 397 / 398 | 925 |
| 6. N-Triples at startup (f7f6573) | 24.8 | 118 / 80 | 138 / 161 | 132 / 187 | 485 / 421 | 1537 |
| 7. SQLite sync at checkpoints (9950549) | 26.6 | 118 / 78 | 136 / 140 | 144 / 182 | 190 / 228 | 1407 |
| 8. reasons in explanations (157328d) | 28.2 | 120 / 57 | 137 / 133 | 146 / 222 | 177 / 254 | 1454 |
| 9. garbage collector freeze (d24c6f8) | 23.4 | 107 / 70 | 64 / 133 | 107 / 191 | 200 / 233 | 263 |
| final (360d256) | 25.2 | 118 / 44 | 94 / 100 | 88 / 149 | 131 / 243 | 498 |

With 5 calls per point and a shared machine, single cells move by ±30% between runs; the trend per step is what matters.

1. **Genre tree fix (correctness, see below).** More films now count as comedy, horror, etc., so there is slightly more work. Kept, because results were wrong without it.
2. **The query scanned every film for every taste.** It started with `?film a wt:Film` joined to the list of tastes, so each taste was tried against all 10,000 films, and genre matching used the property path `wt:hasGenre/wt:subGenreOf*` on both sides. Now each film's genres plus all their parent genres are stored once at startup as `wt:inGenre` (27,300 extra triples for 10k films, under 0.4 s), and each query branch starts from the bound taste. 8 people: 2.1 s → 0.6 s.
3. **Two queries per member.** `rank()` called the graph once for each member's likes and once for their dislikes, so 8 people meant 16 queries, many of them identical (everyone liking drama). Now one query covers all likes in the group and one covers all dislikes; per-member links are set intersections. Explanations (labels and reasons) are built only for the 5 films returned, not for every candidate. 8 people: 0.6 s → 0.2 s.
4. **Python cost per result row.** A big group returns ~47,000 film-taste pairs. Reading rows as tuples and mapping Oxigraph terms straight to ids (no `.value` string per cell) cut that query from 283 to 171 ms in a side-by-side run.
5. **Liked films repeated the same genre lookups.** Eight liked films that are all dramas each fetched the ~5,000 dramas again. Now the first query asks what the liked films share (their genres, directors and cast: ~120 rows), the second reads each needed genre or person once for the whole group, and Python combines the sets. 8 mixed: 290 → 200 ms. (A first version used a variable predicate, `?taste ?relation ?shared`, which made Oxigraph scan every triple: 134 ms for 123 rows. One branch per fixed predicate brought that to 0.6 ms.)
6. **Startup spent 23 s writing Turtle.** The RDF graph was serialised to Turtle (23 s) only to load it into Oxigraph (3 s); rdflib's Turtle writer computes prefixes for every term. N-Triples takes 2.6 s to write and 2.6 s to load. Startup 45 s → 25 s.
7. **Every request waited for the disk.** SQLite in WAL mode synced on every commit, and because each request opened and closed its own connection, the last close also checkpointed and deleted the WAL file (more syncs). The database now keeps one idle connection open and uses `synchronous=NORMAL`, which syncs at checkpoints only. On this disk the recommendation request on the starter catalogue went from ~100 ms to ~15 ms. Trade-off: after a power cut (not an app crash) the last few commits, e.g. votes, can be lost; the database itself stays consistent.
8. **Reasons in explanations** made no difference above the noise (only the 5 returned films are explained).
9. **Garbage collection pauses.** The 10k graph keeps 2.4 million Python objects alive. A full garbage-collection pass over them took ~750 ms and happened at random moments, so some requests took ~1.5 s even though the median was 0.2 s. After startup the app now runs `gc.collect(); gc.freeze()`, which moves those objects out of the collector's view (a full pass then takes ~0 ms). Slowest API call: 1.45 s → 0.26 s.

## Correctness fix found while testing

Disliking a genre did not remove its subgenres on the imported catalogue. The original genre tree had five entries, so `slasher`, `zombie-comedy`, `comedy-horror` or `spaghetti-western` were not linked to horror, comedy or western. `python -m watchtogether.genre_audit` counts what each dislike removed with the old tree and the new one:

| Disliked genre | Films tagged with it | Removed before | Removed now | Got through before |
| --- | ---: | ---: | ---: | ---: |
| horror | 869 | 869 | 991 | 122 |
| comedy | 2031 | 2632 | 3072 | 440 |
| romance | 934 | 1586 | 1598 | 12 |
| western | 272 | 272 | 361 | 89 |
| war | 477 | 477 | 483 | 6 |
| science-fiction | 612 | 637 | 682 | 45 |
| documentary | 218 | 218 | 225 | 7 |
| thriller | 884 | 914 | 1102 | 188 |
| crime | 921 | 995 | 1205 | 210 |
| action | 1262 | 1278 | 1353 | 75 |
| fantasy | 544 | 544 | 564 | 20 |
| drama | 4954 | 4954 | 5258 | 304 |
| pornographic | 43 | 43 | 49 | 6 |

The starter catalogue is unaffected (0 films change).

## Regression budget

`tests/test_big_catalogue.py::test_eight_member_groups_rank_within_budget` fails if the median of 3 calls for either 8-member benchmark group on 10,000 films takes 1 s or more (they took 1.6-1.8 s before; ~0.1-0.15 s now). It runs with the normal test command whenever `data/wikidata.json` is present; the file is in the repository, so the GitHub Actions workflow runs it too; the run for commit 3d51a35 passed on Python 3.11 and 3.12.

## Limits and next steps

- Memory is unchanged at ~0.9-1.0 GB for 10,000 films. Both the rdflib graph (kept for SHACL validation and the importer's Turtle export) and the Oxigraph index hold the whole catalogue; memory was not profiled further.
- Startup is still ~25 s on 10,000 films; a profile puts most of it in building the rdflib graph (roughly 9 s) and SHACL validation (roughly 7 s). Validating once per catalogue version (by its fingerprint) would remove most of that.
- The recommendation endpoint holds the SQLite write lock while it ranks (~0.1 s on 10,000 films), so other groups' writes wait that long during a ranking.
- With many films at the same score, ties are broken by title, so on 10,000 films many 100% matches look alphabetical. Scores are unchanged by this work; a tie-break by match strength would be a product decision.
