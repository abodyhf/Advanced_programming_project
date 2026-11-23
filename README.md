# WatchTogether — Python edition

A working movie-night web app based on your project proposal. Friends enter their likes and dislikes, get a shared shortlist, and vote for one movie.

**Start here:** install Python 3.11 or newer, extract this folder, and open a terminal inside it.

```bash
python -m pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:8000** in your browser. Keep the terminal running. Press Ctrl+C in the terminal to stop.

On macOS/Linux, use `python3` if `python` is not available. On Windows, `py` can also be used instead of `python`. The included `start.bat` (Windows) and `start.sh` (macOS/Linux) create an isolated Python environment and run the app for you; the first launch downloads dependencies.

## Try it in one minute

1. Click **Try a sample group**. You join as “You,” with Ada and Cem as clearly marked sample members.
2. Add or remove a few tastes and click **Save my tastes**.
3. Click **Build our shortlist**. Ada and Cem automatically cast sample votes.
4. Vote for your favorite. The final pick appears.

## Use it with real friends

1. Enter a group name and your nickname on the home page.
2. Choose **Invite friends**, then **Copy invite link** and send it to your friends.
3. Each person joins with a different nickname and selects at least three tastes, including at least one like. Use the genre deck or **Browse catalogue** to search films, genres, actors, or directors.
4. Everyone clicks **Save my tastes**. When 2–8 members are ready, the organiser clicks **Build our shortlist**.
5. Each member votes once. Voting closes automatically when everyone has voted, or the organiser can close it after at least one vote.
6. The film with the most votes wins. A tie goes to the film higher on the shortlist.

The organiser can start a new round, keeping tastes while clearing the shortlist and votes, or delete the whole group. New members and taste edits are locked during voting so the shortlist stays consistent.

To test several people on one computer, open the invitation in a different browser or a separate private window. Membership is stored in **sessionStorage for each tab**. A duplicated tab may inherit the same membership; use a fresh window. Closing the tab loses that membership credential. Rejoining requires a new nickname. Nicknames alone cannot be used to impersonate an existing member.

### Friends on the same Wi-Fi

Run:

```bash
python app.py --host 0.0.0.0
```

Find the computer's local network IP address, for example `192.168.1.20`. Open `http://192.168.1.20:8000` on that computer before creating the group, then share the invitation generated there. `127.0.0.1` only works on the device running Python. Other devices must be on the same reachable network, and the operating system may ask to allow the server through its firewall.

## What is included

| Feature | Implementation |
| --- | --- |
| Groups and invitation links | FastAPI, randomly generated room identifiers, maximum 8 members |
| Taste profiles | Likes/dislikes of films, genres, actors and directors; validated RDF Turtle stored with the membership |
| Movie graph | RDFLib builds RDF and schema.org Movie descriptions; Oxigraph answers SPARQL queries |
| Recommendations | Every candidate must match a like of **each** member; all member dislikes are hard exclusions |
| Fairness and explanations | Score favors the least matched member; each film shows, per person, which likes it connects to and how ("Inception: same director, Christopher Nolan") |
| Voting | One ballot per membership, automatic close, organiser close, deterministic tie handling |
| Durable state | SQLite rooms/profiles/votes survive server restarts |
| Privacy | Nickname and tastes; no e-mail or account registration. Profile SHACL shapes reject extra personal fields |
| Expiry | 30 days of inactivity; cleaned at startup and hourly while the server runs |
| UI | Responsive HTML/CSS/JavaScript served by the Python application; no Node.js or frontend build needed |
| Quality checks | 106 automated tests, incl. an independent reference recommender and the same checks on the 10,000-film catalogue; see `docs/TEST_REPORT.md` |
| Performance | Repeatable benchmark for groups of 2, 4 and 8 on both catalogues; 8 people on 10,000 films rank in 0.09–0.15 s (was 1.6–1.8 s); see `docs/PERFORMANCE_REPORT.md` |

## Movie data and the 10,000-film goal

The app ships with **80 hand-curated starter movies** so recommendations work without any external service. This is a starter catalogue, **not** 10,000 downloaded Wikidata movies. Genres are simplified editorial categories, and cast lists are intentionally partial.

A separate importer fetches real Wikidata records in small SPARQL batches. Wikimedia refuses scripts that do not say who runs them (HTTP 403), so first set a contact e-mail address or URL. It is sent to Wikidata in the User-Agent header and is not stored in the project:

```bash
setx WATCHTOGETHER_CONTACT "you@example.com"     # Windows, then open a new terminal
export WATCHTOGETHER_CONTACT="you@example.com"   # macOS/Linux
```

Start small, then check the records (duplicate IDs, missing title/year/genres/directors/actors, SHACL):

```bash
python -m watchtogether.import_wikidata --limit 100
python -m watchtogether.validate_catalog
```

For the proposal's intended data volume:

```bash
python -m watchtogether.import_wikidata --limit 10000 --batch-size 100
```

The importer keeps English-labeled films with a publication year, director, cast member, and genre. It preserves Wikidata identifiers for imported films and people, normalizes genre labels into local categories, saves progress after each batch, retries temporary service errors, and validates/export the RDF graph with SHACL. Run the same command to resume. It writes `data/wikidata.json` and a Turtle export beside it; it preserves `data/catalog.json`.

Restart the app after importing. It automatically uses `data/wikidata.json` if it exists. To choose a different catalogue, set the `WATCHTOGETHER_CATALOG` environment variable to its absolute path. `GET /api/health` reports the actual film count and data source. A partially completed import can be used, but it may offer fewer matches.

If a catalogue change removes selected entities, affected profiles are marked unfinished and their groups return to collecting tastes. Save updated tastes before starting the next round.

Live Wikidata access depends on connectivity and the public endpoint. The included test suite verifies the importer with controlled SPARQL responses. A live import of 10,000 valid films was completed and validated on 15 November 2026; see `docs/IMPORT_REPORT.md` for the count, validation results, timings and known limits.

## How the recommendations work

1. SPARQL queries match movies to each member's liked entities. A liked film connects to itself and films sharing a genre, director, or cast member. Liked actors/directors match films they appear in or direct. Genres include their subgenres: the startup step stores each film's genres plus every parent genre (`wt:inGenre`), so queries need no property paths.
2. A disliked genre excludes films in that genre or any of its subgenres; a disliked person excludes their films. A disliked film excludes that exact film, rather than every film resembling it.
3. Each remaining film must match **at least one like from every member**. Otherwise it is excluded.
4. A member's match is the fraction of their weighted likes that connect to that film. Person preferences have weight 2; genre and film preferences have weight 1. Each input like counts at most once, even if several graph paths match it.
5. The group score is `100 × (0.6 × lowest member match + 0.4 × average member match)`.
6. Return up to five films, highest score first. If none qualify, the host can explicitly start a compromise ballot. It still respects every Avoid. It requires at least one guest to match and ranks by how many guests match, then by taste score. If no film qualifies even then, the group can review its tastes and try again.

Subgenres come from a small hand-written table (slasher, zombie and vampire are horror; cyberpunk is science fiction, ...) plus the genre names themselves: an imported genre such as `comedy-horror` or `spaghetti-western` is a kind of every catalogue genre spelled inside it. Without this, a horror dislike let 122 of the 10,000 films through (`python -m watchtogether.genre_audit` lists every genre).

Each shortlist card says how every like reaches the film: `this film`, `directs it`, `in the cast`, `via Psychological Thriller` (a subgenre), or for a liked film `same director: …; shared cast: …; shared genre: …`.

These percentages describe graph preference overlap. They are **not measured probabilities of enjoyment**. No language-model API, machine-learning training, or paid key is needed. The supplied OWL ontology describes the domain; the implemented inference is the explicit genre hierarchy, materialised for SPARQL at startup, rather than a general OWL reasoner.

## Project files

```text
app.py                         Run the Python server
watchtogether/api.py            Routes, membership, profiles, voting, expiry task
watchtogether/db.py             SQLite schema and atomic transactions
watchtogether/graph.py          RDF graph construction, SHACL, SPARQL
watchtogether/recommender.py    Group scoring and explanations
watchtogether/import_wikidata.py Resumable external-data importer
watchtogether/validate_catalog.py Duplicate/missing-field and SHACL checks for a catalogue
watchtogether/cleanup.py        Scheduled deletion command
watchtogether/examples.py       Worked example groups with expected shortlists
watchtogether/benchmark.py      Repeatable timing for groups of 2, 4 and 8
watchtogether/genre_audit.py    What a genre dislike removes, before/after the genre tree
data/catalog.json              80-film offline starter catalogue
data/ontology.ttl               OWL domain vocabulary
data/shapes.ttl                 Film and closed-profile SHACL constraints
static/                        Browser interface
tests/                         API, recommendation, concurrency, importer tests
docs/                          Design, verification, and API notes
```

Runtime room data is created in `instance/watchtogether.sqlite3`. It is not bundled in this download. `WATCHTOGETHER_DATA_DIR` selects a different runtime directory. Movie JSON is the durable film-data source; the Oxigraph query index is rebuilt in memory at startup. This keeps this version easy to run with a single server process.

## Run the tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

Tests create isolated temporary databases and do not call the live Wikidata service. `tests/test_big_catalogue.py` repeats the recommendation checks on `data/wikidata.json` (about 30 s to load) and is skipped when that file is absent.

## Examples and measurements

```bash
python -m watchtogether.examples            # shared, conflicting, no-overlap and liked-film groups
python -m watchtogether.benchmark --repeats 10 --out docs/performance/after.json
python -m watchtogether.benchmark --compare docs/performance/baseline.json docs/performance/after.json
python -m watchtogether.genre_audit
```

Results are written up in `docs/EXAMPLES.md` and `docs/PERFORMANCE_REPORT.md`.

## Expiry when the server is not running

An open, authenticated group page counts as activity. Anonymous invitation views do not refresh expiry. Expired groups cannot be revived by a read or join request.

For cleanup independent of the web server, schedule this command with cron or Windows Task Scheduler:

```bash
python -m watchtogether.cleanup
```

Deletion cascades to group members, saved profile RDF, votes and recommendations. SQLite secure deletion and WAL checkpoints are enabled. External backups, if you make them yourself, need their own retention policy.

## API and deployment notes

Interactive API documentation is at `/api/docs` when internet access is available for its Swagger UI assets; the JSON schema is at `/api/openapi.json`. Endpoint notes are in `docs/API.md`.

This download is a working local Python application and an implementation starting point for the course project. It has not been publicly hosted. For an internet deployment, use a Python-capable host, one application worker, a persistent writable data directory, HTTPS, and deployment-specific rate limits. Membership uses random bearer credentials stored as hashes on the server; it does not verify real-world identity. “One vote” means one vote per membership.

Course milestones still requiring your team: real-group usability/satisfaction studies, team review, and repository release. No claimed survey results or team approvals are fabricated.

## Technical references

- [FastAPI](https://fastapi.tiangolo.com/)
- [RDFLib](https://rdflib.readthedocs.io/)
- [Oxigraph Python API](https://pyoxigraph.readthedocs.io/)
- [pySHACL](https://github.com/RDFLib/pySHACL)
- [Wikidata Query Service](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service)
- [Wikidata movie properties](https://www.wikidata.org/wiki/Wikidata:WikiProject_Movies/Properties)

Wikidata structured data is CC0. This project does not include film files, poster image files, or streaming availability data.

### Film pictures

```bash
python -m watchtogether.add_images
```

This stores a picture address (never the image file) for each imported film. Without further setup it uses Wikidata's free Wikimedia Commons images, which cover about 18% of films and are often stills rather than posters. For real posters, create a free account at themoviedb.org, copy its "API Read Access Token" into the `TMDB_TOKEN` environment variable, and run the command again. TMDB requires the notice "This product uses the TMDB API but is not endorsed or certified by TMDB" wherever its images are shown. Films without a picture keep the built-in genre artwork. The delivered dataset has picture addresses for 9,917 of its 10,000 films (9,909 from TMDB).
