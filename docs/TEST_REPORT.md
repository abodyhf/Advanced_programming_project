# Verification report

Date: 13 November 2026. Environment: Linux, Python 3.12, dependencies pinned in requirements.txt. This report describes the generated implementation; it is not a team review or a user study.

## Automated checks

Command: `python -m pytest tests -q --tb=short`

**57 tests passed in 6.44 seconds.** Dependency deprecation warnings were reported by Starlette/RDFLib; no tests failed. `python -m pip check` reported no broken requirements. Python modules imported and executed, `node --check static/app.js` passed, and `bash -n start.sh` passed.

Covered behavior:

- Film, genre, actor and director search, plus query text containing SPARQL-like characters.
- Room creation, normalized/duplicate nicknames, public summary privacy, scoped membership credentials, full groups, and concurrent joins never exceeding eight members.
- Preference requirements, duplicate/contradictory/unknown entity rejection, saved RDF, and closed SHACL rejection of extra e-mail data.
- Incomplete/single-member group rejection, organiser permissions, up to five recommendations, per-member explanations, hard dislikes, genre ancestry, liked-film similarity and exact-film dislikes.
- Membership/profile freeze during voting, invalid-film and duplicate-vote rejection, concurrent duplicate voting, majority results, higher-score tie breaking, and organiser close.
- New rounds, persistence across application restarts, catalogue-change invalidation, expired-group rejection, cascading deletion, cleanup boundaries, and owner-only deletion.
- Explicit sample participants, demo completion with one real vote, and a one-film catalogue fallback.
- Wikidata parsing, stable imported identifiers, skipping incomplete records, retry handling, non-retryable failures, saved/reloadable SHACL-valid imports, and refusal to overwrite unrelated output files.

## Recommendation timing

A separate local API request with eight ready members and the bundled 80-film graph returned five recommendations in **0.017 seconds**. Each profile liked comedy, adventure and drama, and disliked horror. Raw measurement: `benchmark.json`.

This measures the small starter catalogue only. No 10,000-film startup/memory/query benchmark was performed, and this result does not establish performance at the proposal's target size.

## Browser check

Opened the real Python app in Chrome and verified the homepage, sample group, preference selection, unsaved-change gating, saving, recommendation cards, per-person explanations, voting and final-pick banner. Added Animation to the sample profile, saved, requested movies, expanded a match explanation, and cast a vote. The final banner showed **Hunt for the Wilderpeople**, with two of three votes. All three sample-room memberships showed that their votes were in. The demo clearly labeled Ada and Cem as sample members.

Desktop visual layout was inspected. Responsive styles are included, but this build did not perform a separate real-device/mobile browser check. Windows/macOS launcher execution was not tested on those operating systems.

## Live Wikidata check and limits

A real import requesting five films was attempted. The public endpoint ultimately returned **HTTP 429 Too Many Requests**, so no live dataset could be verified here. No 10,000-film download is included. Importer behavior was tested with controlled SPARQL responses, and it remains available for use when the service permits requests.

The shipped catalogue contains exactly **80 manually curated films**. Satisfaction targets, time-to-agreement targets with real users, classroom grading criteria, peer approvals, and production hosting remain unverified.
