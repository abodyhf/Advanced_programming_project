"""Record checks for a film catalogue; exits 1 if any record is invalid.

python -m watchtogether.validate_catalog                 # data/wikidata.json
python -m watchtogether.validate_catalog data/catalog.json --skip-shacl
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from .graph import ROOT, GraphStore

LIST_FIELDS = {"genres": "genres", "directors": "directors", "cast": "actors"}

def check_records(films):
    """Return {problem: [film ids]} for every record-level defect found."""
    problems = {}
    def flag(problem, film):
        problems.setdefault(problem, []).append(str(film.get("id") or film.get("title") or "?"))
    counts = Counter(film.get("id") for film in films)
    for film in films:
        film_id = film.get("id")
        if not isinstance(film_id, str) or not film_id.strip():
            flag("missing id", film)
        elif counts[film_id] > 1:
            flag("duplicate id", film)
        title = film.get("title")
        if not isinstance(title, str) or not title.strip():
            flag("missing title", film)
        year = film.get("year")
        if not isinstance(year, int) or isinstance(year, bool):
            flag("missing year", film)
        elif not 1870 <= year <= 2100:
            flag("implausible year", film)
        for field, name in LIST_FIELDS.items():
            values = film.get(field)
            if not isinstance(values, list) or not values:
                flag("missing " + name, film)
            elif any(not isinstance(value, str) or not value.strip() for value in values):
                flag("blank entry in " + name, film)
        for field in ("directors", "cast"):
            ids = film.get(field + "_ids")
            if ids is not None and len(ids) != len(film.get(field) or []):
                flag(f"{field} names and identifiers differ in length", film)
            if ids and len(set(ids)) != len(ids):
                flag(f"repeated person in {field}", film)
    return problems

def summarize(films):
    return {"films": len(films),
            "unique_ids": len({film.get("id") for film in films}),
            "year_range": [min((f["year"] for f in films if isinstance(f.get("year"), int)), default=None),
                           max((f["year"] for f in films if isinstance(f.get("year"), int)), default=None)],
            "distinct_genres": len({g for f in films for g in f.get("genres") or []}),
            "distinct_directors": len({p for f in films for p in f.get("directors_ids") or f.get("directors") or []}),
            "distinct_actors": len({p for f in films for p in f.get("cast_ids") or f.get("cast") or []})}

def main():
    if hasattr(sys.stdout, "reconfigure"):  # Film titles may not fit a piped Windows console encoding.
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", nargs="?", type=Path, default=ROOT / "data/wikidata.json")
    parser.add_argument("--skip-shacl", action="store_true", help="Only run the fast record checks")
    args = parser.parse_args()
    films = json.loads(args.catalogue.read_text(encoding="utf-8"))["films"]
    problems = check_records(films)
    report = {"catalogue": args.catalogue.name, **summarize(films),
              "problems": {name: {"count": len(ids), "examples": ids[:5]} for name, ids in problems.items()}}
    if not args.skip_shacl and not problems:
        try:
            GraphStore(args.catalogue)
            report["shacl"] = "passed"
        except ValueError as error:
            report["shacl"] = "FAILED: " + str(error)[:500]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    valid = not problems and not str(report.get("shacl", "")).startswith("FAILED")
    print("VALID" if valid else "INVALID")
    sys.exit(0 if valid else 1)

if __name__ == "__main__":
    main()
