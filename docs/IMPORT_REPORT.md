# Catalogue expansion report

Date: 15 November 2026. Environment: Windows 11, Python 3.14.3, pinned requirements in `.venv`.

## Result

**10,000 valid real movies** were imported from Wikidata into `data/wikidata.json` (11.3 MB), with an RDF copy in `data/wikidata.ttl` (21.6 MB). All 10,000 records pass validation. The app loads the dataset and its searches work. The 80-film starter catalogue `data/catalog.json` is unchanged.

## Source

Wikidata Query Service (`https://query.wikidata.org/sparql`), licence CC0, through the existing importer `watchtogether/import_wikidata.py`. A film is kept only if it has an English title, a release year, and at least one director, cast member and genre. Every record keeps its Wikidata identifier and link.

The importer scanned **14,878** Wikidata films to collect 10,000. The other 4,878 were repeats of films already saved or lacked an English label.

## Validation results

Command: `python -m watchtogether.validate_catalog`

| Check | Result |
| --- | --- |
| Records | 10,000 |
| Unique IDs | 10,000 (0 duplicates) |
| Missing title / year / genres / directors / actors | 0 / 0 / 0 / 0 / 0 |
| Blank names, mismatched name/ID lists, repeated people in a film | 0 |
| SHACL (film shape) | passed |
| Year range | 1903 to 2016 |
| Distinct genres / directors / actors | 320 / 5,407 / 47,573 |
| Automated tests | 64 passed (57 before this work) |

The first 100 imported movies were checked the same way before scaling up: 100 unique IDs, no missing fields, SHACL passed.

## Resume check

- **Live:** the real import was hard-killed after 45 seconds. The saved file parsed correctly (423 films, offset 600, no leftover `.tmp`). Running the same command continued from offset 600.
- **Unplanned:** a later run stopped at 1,599 films on a cut-off answer from Wikidata. The file was intact and the next run continued from there.
- **Offline:** a new test simulates a dropped connection and checks that nothing already saved is downloaded again.

## App check on the new catalogue

- `/api/health` reports 10,000 films, source "Wikidata (CC0)".
- Start-up takes about 17 seconds (building the graph and SHACL); it was under 1 second with 80 films.
- Searches answer in 11 to 18 ms. Examples: film "iron man" returns Iron Man (2008), Iron Man 3 (2013) and Tetsuo: The Iron Man (1989); director "hitchcock" returns Alfred Hitchcock; actor "tom hanks" returns Tom Hanks.
- Checked in a browser: home page, sample group, Films search, and the new "Load more" button.
- Sample-group recommendations return five films in 0.4 seconds.

## Importer fixes

| Fix | Why |
| --- | --- |
| Contact sent in the User-Agent (`WATCHTOGETHER_CONTACT` or `--contact`) | Wikimedia answered HTTP 403 to every request without one |
| Paging query no longer sorts all films | The sorted query timed out (three 50-second timeouts); the unsorted one answers in 1 to 14 seconds |
| Cut-off answers (HTTP 200 with broken JSON) are retried | One stopped the import at 1,599 films |
| Retries are printed; a 403 explains what to do | Silent retries hid why runs were slow |
| Progress output is ASCII and never fails on encoding | On Windows, piping the output crashed the importer |
| "children's film" becomes `childrens` | It was stored as `children-s` |
| New `validate_catalog` command | Repeatable record checks plus SHACL |
| Tests pinned to the starter catalogue | They would otherwise run against the imported file and fail |

## App fixes made along the way

- JavaScript is now served as `text/javascript`. On this PC Windows registered `.js` as plain text, so the page stayed on "Getting the popcorn ready".
- `start.bat` stops an earlier copy of the app on port 8000 and opens the browser.
- Search results have a "Load more" button (24 more per click).

## Film pictures

`python -m watchtogether.add_images` added a picture address to **9,917 of the 10,000 films**: 9,909 posters from TMDB (matched through the TMDB identifier stored in Wikidata) and 8 free Wikimedia Commons images where TMDB had none. 83 films have no picture and keep the built-in artwork. Only addresses are stored; no image files and no API token are in the project. The token is read from the `TMDB_TOKEN` environment variable.

Checked in a browser: all 24 results of a Films search for "star" showed a poster, and all 5 shortlist cards of the sample group showed one. The page carries the notice TMDB requires. The dataset was re-validated after this step: still VALID (10,000 unique IDs, no missing fields, SHACL passed).

Posters are copyrighted and are shown by link through TMDB's API under its terms of use; they must not be copied into the submission.

## Problems and limits

1. **Not a popularity-ranked set.** Films come in Wikidata's own order, so the mix leans toward older and European titles, and some famous films are absent (for example, "The Godfather" is not among the 10,000).
2. **No fixed order.** Wikidata's servers return the unsorted pages in different orders, so about a third of scanned films were repeats or skipped. A rerun from scratch will not give exactly the same 10,000.
3. **Cast data is as Wikidata has it.** Lists are not in billing order and sometimes include people seen only in archive footage. Cast sizes range from 1 to 123.
4. **Genre noise.** 95 of the 320 genres are used by a single film, and a few tags are odd. 49 films carry a pornographic genre tag; consider filtering them before a classroom demo.
5. **Same title and year.** Five pairs share both (for example the English and Spanish "Dracula" of 1931). They are different Wikidata films with different IDs, not duplicates.
6. **Service instability.** The final run needed 9 retries (HTTP 502, HTTP 429, cut-off answers) and took 35 minutes for the last 8,400 films.
7. **Start-up time** grew to about 17 seconds at this size.
8. `.gitignore` excludes `data/wikidata.json` and `data/wikidata.ttl`. Remove those two lines if the dataset must be submitted through git.
9. `start.bat` was run by its owner and started the app, but its "stop the earlier copy" branch was not observed in a test.

## Reproduce

```powershell
setx WATCHTOGETHER_CONTACT "your-email-address"
```

In a new terminal in the project folder:

```powershell
.venv\Scripts\python.exe -m watchtogether.import_wikidata --limit 10000
.venv\Scripts\python.exe -m watchtogether.validate_catalog
```

If the import stops, run the same command again; it resumes.
