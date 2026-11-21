"""Add a picture address to each imported film; resumable, nothing is downloaded.

python -m watchtogether.add_images

Step 1 (always): Wikidata's own image (P18, free Wikimedia Commons files) and TMDB id (P4947).
Step 2 (only if the TMDB_TOKEN environment variable holds a TMDB "API Read Access Token"):
real posters from The Movie Database for films that have a TMDB id.

Only addresses are stored in data/wikidata.json. The browser loads the pictures from
Wikimedia or TMDB when a film is shown.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote
import httpx
from .graph import ROOT
from .import_wikidata import CONTACT_ENV, ENDPOINT, build_user_agent, select

TMDB_ENV = "TMDB_TOKEN"
TMDB_API = "https://api.themoviedb.org/3/movie/"
TMDB_IMAGES = "https://image.tmdb.org/t/p/w342"
PICTURE_TYPES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".tif", ".tiff")

def commons_url(value, width=400):
    """Turn Wikidata's Commons file link into an https thumbnail address, or None for video/audio."""
    name = unquote(value.rsplit("/", 1)[-1])
    if not name.lower().endswith(PICTURE_TYPES):
        return None
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name)}?width={width}"

def save(path, catalog):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)

def add_wikidata_images(catalog, path, client, batch_size=200):
    """Films get image_checked=True once looked up, so an interrupted run continues where it stopped."""
    todo = [film for film in catalog["films"]
            if not film.get("image_checked") and re.fullmatch(r"film:Q\d+", film["id"])]
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        values = " ".join("wd:" + film["id"][5:] for film in batch)
        rows = select(client, f"""SELECT ?film (SAMPLE(?i) AS ?image) (SAMPLE(?t) AS ?tmdb) WHERE {{
            VALUES ?film {{ {values} }}
            OPTIONAL {{ ?film wdt:P18 ?i }} OPTIONAL {{ ?film wdt:P4947 ?t }} }} GROUP BY ?film""")
        found = {row["film"]["value"].rsplit("/", 1)[-1]: row for row in rows}
        for film in batch:
            row = found.get(film["id"][5:], {})
            image = commons_url(row["image"]["value"]) if "image" in row else None
            if image:
                film["image"], film["image_source"] = image, "Wikimedia Commons"
            if "tmdb" in row and re.fullmatch(r"\d+", row["tmdb"]["value"]):
                film["tmdb_id"] = row["tmdb"]["value"]
            film["image_checked"] = True
        save(path, catalog)
        print(f"Wikidata: checked {min(start + batch_size, len(todo)):,} of {len(todo):,} films", flush=True)
        time.sleep(1)

def add_tmdb_posters(catalog, path, token, transport=None):
    """A TMDB poster replaces a Wikidata picture (those are often stills or logos, not posters)."""
    todo = [film for film in catalog["films"] if film.get("tmdb_id") and not film.get("tmdb_checked")]
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=30, transport=transport) as client:
        for count, film in enumerate(todo, 1):
            response = client.get(TMDB_API + film["tmdb_id"])
            if response.status_code == 429:
                time.sleep(int(response.headers.get("Retry-After", "2") or 2))
                response = client.get(TMDB_API + film["tmdb_id"])
            if response.status_code == 401:
                raise ValueError(f"TMDB rejected the token in {TMDB_ENV}")
            if response.status_code == 200:
                poster = response.json().get("poster_path")
                if isinstance(poster, str) and re.fullmatch(r"/[\w.-]+", poster):
                    film["image"], film["image_source"] = TMDB_IMAGES + poster, "TMDB"
            if response.status_code in (200, 404):
                film["tmdb_checked"] = True
            if count % 100 == 0 or count == len(todo):
                save(path, catalog)
                print(f"TMDB: checked {count:,} of {len(todo):,} films", flush=True)

def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("catalogue", nargs="?", type=Path, default=ROOT / "data/wikidata.json")
    parser.add_argument("--contact", default=os.environ.get(CONTACT_ENV))
    args = parser.parse_args()
    if not (args.contact or "").strip():
        parser.error(f"Set the {CONTACT_ENV} environment variable or pass --contact (Wikimedia requires it).")
    try:
        catalog = json.loads(args.catalogue.read_text(encoding="utf-8"))
        if catalog.get("_import", {}).get("endpoint") != ENDPOINT:
            raise ValueError("This file was not created by the Wikidata importer")
        headers = {"Accept": "application/sparql-results+json", "User-Agent": build_user_agent(args.contact)}
        with httpx.Client(headers=headers, timeout=60, follow_redirects=True) as client:
            add_wikidata_images(catalog, args.catalogue, client)
        token = os.environ.get(TMDB_ENV, "").strip()
        if token:
            add_tmdb_posters(catalog, args.catalogue, token)
        else:
            print(f"No {TMDB_ENV} set: skipped TMDB posters.")
    except (httpx.HTTPError, ValueError, KeyError, OSError) as error:
        print(f"Stopped: {error}\nProgress is saved. Run the same command to continue.", file=sys.stderr)
        sys.exit(1)
    films = catalog["films"]
    print(f"{sum(1 for f in films if f.get('image')):,} of {len(films):,} films have a picture "
          f"({sum(1 for f in films if f.get('image_source') == 'TMDB'):,} from TMDB). Restart the app to see them.")

if __name__ == "__main__":
    main()
