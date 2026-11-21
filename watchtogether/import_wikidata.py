"""Resumable, politely batched Wikidata import; no API key needed.

python -m watchtogether.import_wikidata --limit 10000
The starter catalogue stays untouched; the app detects data/wikidata.json.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
import httpx
from .graph import ROOT, GraphStore, slug

ENDPOINT = "https://query.wikidata.org/sparql"
PREFIX = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX bd: <http://www.bigdata.com/rdf#>
"""
PROPERTIES = {"P57": "directors", "P161": "cast", "P136": "genres", "P577": "years"}
CONTACT_ENV = "WATCHTOGETHER_CONTACT"

def build_user_agent(contact):
    """Wikimedia's User-Agent policy: client/version (contact) library/version.

    Requests without a reachable contact (e-mail or URL) are refused with 403.
    """
    contact = " ".join(str(contact).split())
    if not contact or any(ord(char) < 32 or ord(char) > 126 for char in contact):
        raise ValueError("The contact must be a plain e-mail address or URL")
    return f"WatchTogether/1.0 ({contact}; educational film knowledge graph) httpx/{httpx.__version__}"

def genre_key(label):
    label = re.sub(r"\s+(film|films|movie|cinema)$", "", label.lower().strip())
    return slug(re.sub(r"['’]", "", label))  # "children's film" -> "childrens", not "children-s"

def select(client, query, attempts=4):
    for attempt in range(attempts):
        try:
            response = client.get(ENDPOINT, params={"query": PREFIX + query, "format": "json"})
            if response.status_code in (429, 500, 502, 503, 504):
                if attempt == attempts - 1:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After", "")
                delay = min(int(retry_after), 30) if retry_after.isdigit() else 5 * (attempt + 1)
                print(f"Endpoint busy ({response.status_code}); retrying in {delay}s...", flush=True)
                time.sleep(delay)
                continue
            if response.status_code == 403:
                # Not retried: Wikimedia refuses clients that do not identify themselves.
                raise httpx.HTTPStatusError(
                    "Wikidata refused the request (HTTP 403): " + response.text.strip()[:200] +
                    f"\nIdentify yourself: set the {CONTACT_ENV} environment variable (or --contact) "
                    "to an e-mail address or URL where Wikimedia can reach you.",
                    request=response.request, response=response)
            response.raise_for_status()
            try:
                return response.json()["results"]["bindings"]
            except ValueError as error:
                # The service sometimes cuts a large answer off mid-stream; it still says HTTP 200.
                raise httpx.DecodingError(f"Incomplete answer from Wikidata ({error})") from error
        except (httpx.TransportError, httpx.DecodingError) as error:
            if attempt == attempts - 1:
                raise
            delay = 3 * (attempt + 1)
            print(f"{type(error).__name__}; retrying in {delay}s...", flush=True)
            time.sleep(delay)

def parse_films(rows):
    records = {}
    for row in rows:
        qid = row["film"]["value"].rsplit("/", 1)[-1]
        if not re.fullmatch(r"Q\d+", qid):
            continue
        title = row.get("filmLabel", {}).get("value", qid)
        if title == qid:
            continue  # Require a usable English title.
        record = records.setdefault(qid, {"id": "film:" + qid, "title": title,
                         "directors": [], "directors_ids": [], "cast": [], "cast_ids": [],
                         "genres": [], "years": [], "wikidata": "https://www.wikidata.org/wiki/" + qid,
                         "source": "Wikidata (CC0)"})
        prop = row["property"]["value"].rsplit("/", 1)[-1]
        field = PROPERTIES.get(prop)
        if field is None:
            continue
        value = row["value"]["value"]
        if field == "years":
            match = re.match(r"^(\d{4})-", value)
            if match and 1870 <= int(match[1]) <= 2100:
                record["years"].append(int(match[1]))
        else:
            entity_id = value.rsplit("/", 1)[-1]
            label = row.get("valueLabel", {}).get("value", entity_id)
            if label == entity_id or not re.fullmatch(r"Q\d+", entity_id):
                continue
            if field == "genres":
                genre = genre_key(label)
                if genre and genre not in record["genres"]:
                    record["genres"].append(genre)
            elif "person:" + entity_id not in record[field + "_ids"]:
                record[field].append(label)
                record[field + "_ids"].append("person:" + entity_id)
    films = []
    for record in records.values():
        if not all(record[field] for field in ["directors", "cast", "genres", "years"]):
            continue
        record["year"] = min(record.pop("years"))
        films.append(record)
    return films

def import_catalog(limit=10000, batch_size=100, output=None, user_agent=None):
    output = Path(output or ROOT / "data/wikidata.json")
    if output.resolve() == (ROOT / "data/catalog.json").resolve():
        raise ValueError("Choose another output file to preserve the starter catalogue")
    films, offset = {}, 0
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing.get("_import", {}).get("endpoint") != ENDPOINT:
            raise ValueError("Output file was not created by this importer; choose another path")
        films = {film["id"]: film for film in existing["films"]}
        offset = existing["_import"]["offset"]
    headers = {"Accept": "application/sparql-results+json",
               "User-Agent": user_agent or "WatchTogether/1.0 (educational film knowledge graph; Python httpx)"}
    with httpx.Client(headers=headers, timeout=50, follow_redirects=True) as client:
        while len(films) < limit:
            size = min(batch_size, limit - len(films))
            # No ORDER BY: sorting every Wikidata film exceeds the service's 60 s limit, while the
            # unsorted scan streams and stops at LIMIT. The public servers do not all return the
            # same order, so a page can repeat films (dropped by id below) or skip some (harmless:
            # any complete film is acceptable).
            ids = select(client, f"""SELECT ?film WHERE {{
                ?film wdt:P31 wd:Q11424 .
                FILTER EXISTS {{ ?film wdt:P57 [] }}
                FILTER EXISTS {{ ?film wdt:P161 [] }}
                FILTER EXISTS {{ ?film wdt:P136 [] }}
                FILTER EXISTS {{ ?film wdt:P577 [] }}
            }} LIMIT {size} OFFSET {offset}""")
            if not ids:
                break
            qids = [row["film"]["value"].rsplit("/", 1)[-1] for row in ids]
            if any(not re.fullmatch(r"Q\d+", qid) for qid in qids):
                raise ValueError("Unexpected film identifier from Wikidata")
            values = " ".join("wd:" + qid for qid in qids)
            # Single property per row avoids cast × director × genre multiplication.
            rows = select(client, f"""SELECT ?film ?filmLabel ?property ?value ?valueLabel WHERE {{
                VALUES ?film {{ {values} }}
                VALUES ?property {{ wdt:P57 wdt:P161 wdt:P136 wdt:P577 }}
                ?film ?property ?value .
                SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }}""")
            for film in parse_films(rows):
                films[film["id"]] = film
            offset += len(ids)
            output.parent.mkdir(parents=True, exist_ok=True)
            payload = {"source": "Wikidata (CC0); imported with WatchTogether", "films": list(films.values()),
                       "_import": {"endpoint": ENDPOINT, "offset": offset, "license": "CC0"}}
            temporary = output.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(output)
            # ASCII only: a piped Windows console (cp1252) cannot encode arrows and would abort the run.
            print(f"Saved {len(films):,} valid films (scanned {offset:,}) -> {output.name}", flush=True)
            if len(films) < limit:
                time.sleep(1)
    if not films:
        raise ValueError("No usable films were returned. The starter catalogue still works.")
    # Build/validate the actual graph and save an interoperable Turtle export.
    graph = GraphStore(output)
    graph.rdf.serialize(destination=output.with_suffix(".ttl"), format="turtle")
    print(f"SHACL passed for {len(films):,} films. Restart the app to use this catalogue.")
    if len(films) < limit:
        raise ValueError(f"The endpoint returned only {len(films)} usable films, below the requested {limit}.")
    return output

def main():
    for stream in (sys.stdout, sys.stderr):  # Never let an unencodable character stop an import.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--contact", default=os.environ.get(CONTACT_ENV),
                        help=f"E-mail address or URL sent to Wikimedia in the User-Agent (default: ${CONTACT_ENV})")
    parser.add_argument("--user-agent", help="Full User-Agent header, replacing the one built from --contact")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100000 or not 1 <= args.batch_size <= 200:
        parser.error("Use a limit of 1-100000 and a batch size of 1-200")
    if not args.user_agent and not (args.contact or "").strip():
        parser.error(f"Wikimedia blocks anonymous scripts (HTTP 403). Set the {CONTACT_ENV} environment "
                     "variable, or pass --contact, with an e-mail address or URL where you can be reached.")
    try:
        user_agent = args.user_agent or build_user_agent(args.contact)
        import_catalog(args.limit, args.batch_size, args.output, user_agent)
    except (httpx.HTTPError, ValueError, KeyError, OSError) as error:
        print(f"Import stopped: {error}\nAny completed batches remain saved. Run the same command to resume. The bundled catalogue is unchanged.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
