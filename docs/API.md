# API notes

All API paths begin with `/api`. JSON bodies use `Content-Type: application/json`.

Creating or joining a group returns a `token`, `member_id`, and `group_id`. Supply `Authorization: Bearer YOUR_TOKEN` on subsequent member requests. Do not put credentials in invitation links. A membership credential is scoped to one group.

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/health` | Actual film count, source and catalogue fingerprint | Public |
| GET | `/catalog?q=...&kind=genre` | Search; kinds: all, film, genre, actor, director | Public |
| POST | `/groups` | JSON: `title`, `nickname`; create room and host | Public |
| POST | `/groups/{id}/members` | JSON: `nickname`; join collecting room | Invitation holder |
| GET | `/groups/{id}` | Public room summary; authenticated full group state | Invitation holder / member |
| PUT | `/groups/{id}/profile` | JSON: `likes: [entity IDs]`, `dislikes: [entity IDs]` | Member; collecting only |
| GET | `/groups/{id}/profile.ttl` | Download own validated RDF profile | Member |
| POST | `/groups/{id}/recommendations` | Freeze profiles and make shortlist | Organiser |
| POST | `/groups/{id}/votes` | JSON: `film_id`; cast one ballot | Member; voting only |
| POST | `/groups/{id}/close` | Close early if at least one vote exists | Organiser |
| POST | `/groups/{id}/reset` | New round; clears votes/shortlist, retains tastes | Organiser |
| DELETE | `/groups/{id}` | Delete room and all associated data | Organiser |
| POST | `/demo` | Create explicitly labeled room with sample participants | Public |

Creation/join/vote return 201. Invalid input returns 422; missing/invalid credentials 401; organiser-only actions by another member 403; unknown rooms 404; invalid round operations, group limits, or incomplete profiles 409; expired rooms 410. The response's `detail` explains the problem. Requests with declared bodies above 32 KiB are refused.

Preference IDs must come from `/catalog`. The backend resolves identifiers against its loaded entities before SPARQL use. The UI treats all dynamic names as text, and API responses omit bearer credentials and credential hashes.

Group state is `collecting`, `voting`, or `finished`. Members and tastes freeze during voting. All mutations use a SQLite write transaction, including capacity checks, duplicate vote detection, and automatic close, so simultaneous requests cannot overfill a group or record two votes from one membership.

GET group state returns public membership **counts** without credentials, never the profiles or member list. Authenticated state returns the participant list, the caller's preferences, and group-visible movie explanations. A member cannot read another member's full RDF profile via the export route.

The standard request requires a like from every member. If it finds none, it returns 409 with `X-Recommendation-Conflict: no_full_match` and leaves the room collecting tastes. The organiser can retry with `?allow_compromise=true` to match fewer guests while keeping all avoids. That retry prefers full matches if available, otherwise ranks by guest coverage then score. If it still finds no films, it returns `no_compromise`. In a tied ballot, the earliest film in the saved shortlist wins.

Each shortlist film carries the catalogue fields plus `score` and `matches`, one entry per member:

```json
{"member_id": "…", "nickname": "Ana", "match": 33,
 "because": ["Inception"],
 "reasons": [{"id": "film:inception-2010", "label": "Inception",
              "why": "same director: Christopher Nolan; shared genre: Science fiction"}]}
```

`because` lists the labels of the member's likes that reach the film (kept for older clients); `reasons` adds how each one reaches it: `this film`, `genre`, `via <subgenre>`, `directs it`, `in the cast`, `directs it and is in the cast`, or for a liked film any of `same director: …`, `shared cast: …`, `shared genre: …` joined by `; `.
