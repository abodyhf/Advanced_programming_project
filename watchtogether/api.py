"""REST API and browser UI. No e-mail, passwords, LLM, or API keys required."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import secrets
import time
import unicodedata
import uuid
from typing import Literal
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from .db import Database
from .graph import GraphStore, ROOT
from .recommender import Recommender

# Windows takes file types from the registry, where .js is often "text/plain". Combined with
# the nosniff header below, browsers then refuse to run app.js and the page never loads.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

class Nickname(BaseModel):
    nickname: str = Field(min_length=1, max_length=24)

    @field_validator("nickname")
    @classmethod
    def clean_name(cls, value):
        value = unicodedata.normalize("NFKC", value).strip()
        if not value or any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("Use a nickname with 1 to 24 visible characters")
        return value

class NewGroup(Nickname):
    title: str = Field(min_length=1, max_length=60)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Enter a group name")
        return value

class Profile(BaseModel):
    likes: list[str] = Field(max_length=40)
    dislikes: list[str] = Field(default_factory=list, max_length=40)

class Ballot(BaseModel):
    film_id: str = Field(min_length=1, max_length=150)

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def create_app(data_dir=None, catalog_path=None):
    data_dir = Path(data_dir or os.environ.get("WATCHTOGETHER_DATA_DIR", ROOT / "instance"))
    db = Database(data_dir / "watchtogether.sqlite3")
    db.cleanup()
    imported_catalog = ROOT / "data/wikidata.json"
    default_catalog = imported_catalog if imported_catalog.exists() else ROOT / "data/catalog.json"
    graph = GraphStore(catalog_path or os.environ.get("WATCHTOGETHER_CATALOG") or default_catalog)
    recommender = Recommender(graph)
    # A catalogue switch can change film/person identifiers. Never reuse a stale
    # validated profile against a different set of entities.
    with db.transaction() as connection:
        for person in connection.execute("SELECT id,likes,dislikes FROM members").fetchall():
            old_likes, old_dislikes = json.loads(person["likes"]), json.loads(person["dislikes"])
            known_likes = [item for item in old_likes if item in graph.entities]
            known_dislikes = [item for item in old_dislikes if item in graph.entities]
            if old_likes != known_likes or old_dislikes != known_dislikes:
                connection.execute("UPDATE members SET likes=?,dislikes=?,rdf_ttl=NULL WHERE id=?",
                                   (json.dumps(known_likes), json.dumps(known_dislikes), person["id"]))
                connection.execute("DELETE FROM votes WHERE group_id=(SELECT group_id FROM members WHERE id=?)", (person["id"],))
                connection.execute("UPDATE groups SET phase='collecting',recommendations='[]',winner=NULL WHERE id=(SELECT group_id FROM members WHERE id=?)", (person["id"],))

    @asynccontextmanager
    async def lifespan(app):
        async def expiry_loop():
            while True:
                await asyncio.sleep(3600)
                await asyncio.to_thread(db.cleanup)
        task = asyncio.create_task(expiry_loop())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="WatchTogether", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.db, app.state.graph, app.state.recommender = db, graph, recommender

    @app.middleware("http")
    async def headers(request: Request, call_next):
        if int(request.headers.get("content-length", "0") or "0") > 32768:
            return JSONResponse({"detail": "Request is too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        if not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://commons.wikimedia.org https://upload.wikimedia.org https://thumb.wikimedia.org https://image.tmdb.org; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    def room(connection, group_id):
        group = connection.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
        if group is None:
            raise HTTPException(404, "This group does not exist or has expired")
        if group["last_used"] < time.time() - 30 * 86400:
            raise HTTPException(410, "This group expired after 30 days without activity")
        return group

    def member(connection, group_id, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Join this group first")
        token = authorization[7:]
        if len(token) > 128:
            raise HTTPException(401, "Invalid membership token")
        found = connection.execute("SELECT * FROM members WHERE group_id=? AND token_hash=?", (group_id, digest(token))).fetchone()
        if found is None:
            raise HTTPException(401, "This session cannot access this group. Join with a new nickname.")
        connection.execute("UPDATE groups SET last_used=? WHERE id=?", (time.time(), group_id))
        return found

    def owner(group, who):
        if group["owner_id"] != who["id"]:
            raise HTTPException(403, "Only the organiser can do that")

    def collecting(group):
        if group["phase"] != "collecting":
            raise HTTPException(409, "Voting has started. The organiser can start a new round to change tastes or members.")

    def insert_member(connection, group_id, nickname):
        if connection.execute("SELECT COUNT(*) FROM members WHERE group_id=?", (group_id,)).fetchone()[0] >= 8:
            raise HTTPException(409, "This group is full (8 people maximum)")
        key = nickname.casefold()
        if connection.execute("SELECT 1 FROM members WHERE group_id=? AND nickname_key=?", (group_id, key)).fetchone():
            raise HTTPException(409, "That nickname is taken in this group. Choose another.")
        member_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        connection.execute("INSERT INTO members (id,group_id,nickname,nickname_key,token_hash) VALUES(?,?,?,?,?)", (member_id, group_id, nickname, key, digest(token)))
        return {"member_id": member_id, "token": token}

    def insert_group(connection, title, nickname, demo=False):
        group_id = secrets.token_urlsafe(12)
        now = time.time()
        connection.execute("INSERT INTO groups (id,title,owner_id,created_at,last_used,is_demo) VALUES(?,?,?,?,?,?)", (group_id, title, "", now, now, int(demo)))
        credentials = insert_member(connection, group_id, nickname)
        connection.execute("UPDATE groups SET owner_id=? WHERE id=?", (credentials["member_id"], group_id))
        return {"group_id": group_id, "join_path": "/g/" + group_id, **credentials}

    def save_profile(connection, who, profile):
        likes, dislikes = profile.likes, profile.dislikes
        if len(set(likes + dislikes)) != len(likes + dislikes):
            raise HTTPException(422, "Choose each taste once, either liked or disliked")
        if not likes or len(likes + dislikes) < 3:
            raise HTTPException(422, "Choose at least 3 tastes, including at least 1 like")
        if any(value not in graph.entities for value in likes + dislikes):
            raise HTTPException(422, "A taste was not found in the movie catalogue")
        rdf_ttl = graph.make_profile(who["id"], who["nickname"], likes, dislikes)
        connection.execute("UPDATE members SET likes=?,dislikes=?,rdf_ttl=? WHERE id=?", (json.dumps(likes), json.dumps(dislikes), rdf_ttl, who["id"]))

    def finalise(connection, group_id):
        group = room(connection, group_id)
        tally = dict(connection.execute("SELECT film_id,COUNT(*) FROM votes WHERE group_id=? GROUP BY film_id", (group_id,)).fetchall())
        if not tally:
            raise HTTPException(409, "At least one person must vote before closing the vote")
        # Shortlist is already ordered by score, title, and identifier. max keeps the first tie.
        shortlist = json.loads(group["recommendations"])
        winner = max(shortlist, key=lambda item: (tally.get(item["id"], 0), item["score"]))
        connection.execute("UPDATE groups SET phase='finished',winner=? WHERE id=?", (winner["id"], group_id))

    @app.get("/api/health")
    def health():
        return {"status": "ok", "films": len(graph.movies), "catalogue_source": graph.source, "catalogue_version": graph.fingerprint}

    @app.get("/api/catalog")
    def search(q: str = Query(default="", max_length=80), kind: Literal["all", "film", "genre", "actor", "director"] = "all",
               offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=24, ge=1, le=100)):
        # One extra result tells the page whether a "Load more" button is worth showing.
        found = graph.search(q, kind, offset + limit + 1)
        return {"items": found[offset:offset + limit], "has_more": len(found) > offset + limit,
                "film_count": len(graph.movies), "source": graph.source}

    @app.post("/api/groups", status_code=201)
    def new_group(body: NewGroup):
        with db.transaction() as connection:
            return insert_group(connection, body.title, body.nickname)

    @app.post("/api/demo", status_code=201)
    def demo():
        demo_likes = ["genre:comedy", "genre:adventure", "genre:drama"]
        demo_dislikes = ["genre:horror"] if "genre:horror" in graph.entities else []
        if not all(item in graph.entities for item in demo_likes):
            if not graph.movies:
                raise HTTPException(409, "Import some films before trying a sample group")
            film_id, first_film = next(iter(graph.movies.items()))
            director = graph.search(first_film["directors"][0], "director", 1)[0]
            demo_likes = [film_id, "genre:" + first_film["genres"][0], director["id"]]
            demo_dislikes = []
        with db.transaction() as connection:
            credentials = insert_group(connection, "The Friday film club", "You", demo=True)
            for nickname in ["Ada", "Cem"]:
                insert_member(connection, credentials["group_id"], nickname)
            people = connection.execute("SELECT * FROM members WHERE group_id=?", (credentials["group_id"],)).fetchall()
            for who in people:
                save_profile(connection, who, Profile(likes=demo_likes, dislikes=demo_dislikes))
            return credentials

    @app.post("/api/groups/{group_id}/members", status_code=201)
    def join(group_id: str, body: Nickname):
        with db.transaction() as connection:
            group = room(connection, group_id)
            collecting(group)
            credentials = insert_member(connection, group_id, body.nickname)
            connection.execute("UPDATE groups SET last_used=? WHERE id=?", (time.time(), group_id))
            return {"group_id": group_id, **credentials}

    @app.get("/api/groups/{group_id}")
    def get_group(group_id: str, authorization: str | None = Header(default=None)):
        with db.transaction() as connection:
            group = room(connection, group_id)
            members = connection.execute("SELECT * FROM members WHERE group_id=? ORDER BY rowid", (group_id,)).fetchall()
            result = {"id": group["id"], "title": group["title"], "phase": group["phase"], "member_count": len(members), "capacity": 8, "is_demo": bool(group["is_demo"])}
            if authorization is None:
                return result
            who = member(connection, group_id, authorization)
            votes = connection.execute("SELECT * FROM votes WHERE group_id=?", (group_id,)).fetchall()
            tally = {}
            for vote in votes:
                tally[vote["film_id"]] = tally.get(vote["film_id"], 0) + 1
            result.update({"owner_id": group["owner_id"], "me": {"id": who["id"], "nickname": who["nickname"], "likes": json.loads(who["likes"]), "dislikes": json.loads(who["dislikes"]), "taste_items": [graph.entities[value] for value in json.loads(who["likes"]) + json.loads(who["dislikes"])], "ready": who["rdf_ttl"] is not None},
                           "members": [{"id": item["id"], "nickname": item["nickname"], "ready": item["rdf_ttl"] is not None, "voted": any(vote["member_id"] == item["id"] for vote in votes)} for item in members],
                           "recommendations": json.loads(group["recommendations"]), "winner": group["winner"], "tally": tally,
                           "my_vote": next((vote["film_id"] for vote in votes if vote["member_id"] == who["id"]), None), "vote_count": len(votes)})
            return result

    @app.put("/api/groups/{group_id}/profile")
    def profile(group_id: str, body: Profile, authorization: str | None = Header(default=None)):
        with db.transaction() as connection:
            group = room(connection, group_id)
            who = member(connection, group_id, authorization)
            collecting(group)
            save_profile(connection, who, body)
            return {"saved": True}

    @app.get("/api/groups/{group_id}/profile.ttl")
    def profile_rdf(group_id: str, authorization: str | None = Header(default=None)):
        with db.transaction() as connection:
            room(connection, group_id)
            who = member(connection, group_id, authorization)
            if who["rdf_ttl"] is None:
                raise HTTPException(404, "Save a taste profile first")
            return Response(who["rdf_ttl"], media_type="text/turtle")

    @app.post("/api/groups/{group_id}/recommendations")
    def recommend(group_id: str, authorization: str | None = Header(default=None)):
        with db.transaction() as connection:
            group = room(connection, group_id)
            who = member(connection, group_id, authorization)
            owner(group, who)
            collecting(group)
            people = connection.execute("SELECT * FROM members WHERE group_id=? ORDER BY rowid", (group_id,)).fetchall()
            if len(people) < 2:
                raise HTTPException(409, "Invite at least one friend before finding movies")
            unready = [person["nickname"] for person in people if person["rdf_ttl"] is None]
            if unready:
                raise HTTPException(409, "Waiting for taste profiles from: " + ", ".join(unready))
            ranked = recommender.rank(people)
            if not ranked:
                raise HTTPException(409, "No film matches everyone while respecting all dislikes. Try more likes or fewer dislikes, or import more films.")
            connection.execute("UPDATE groups SET phase='voting',recommendations=? WHERE id=?", (json.dumps(ranked), group_id))
            if group["is_demo"]:
                for index, person in enumerate(people[1:]):
                    connection.execute("INSERT INTO votes VALUES(?,?,?)", (group_id, person["id"], ranked[index % len(ranked)]["id"]))
            return {"recommendations": ranked}

    @app.post("/api/groups/{group_id}/votes", status_code=201)
    def vote(group_id: str, body: Ballot, authorization: str | None = Header(default=None)):
        with db.transaction() as connection:
            group = room(connection, group_id)
            who = member(connection, group_id, authorization)
            if group["phase"] != "voting":
                raise HTTPException(409, "There is no open vote in this group")
            if connection.execute("SELECT 1 FROM votes WHERE group_id=? AND member_id=?", (group_id, who["id"])).fetchone():
                raise HTTPException(409, "You have already voted in this round")
            if body.film_id not in {movie["id"] for movie in json.loads(group["recommendations"])}:
                raise HTTPException(422, "Choose a movie from this group's shortlist")
            connection.execute("INSERT INTO votes VALUES(?,?,?)", (group_id, who["id"], body.film_id))
            count = connection.execute("SELECT COUNT(*) FROM votes WHERE group_id=?", (group_id,)).fetchone()[0]
            people = connection.execute("SELECT COUNT(*) FROM members WHERE group_id=?", (group_id,)).fetchone()[0]
            if count == people:
                finalise(connection, group_id)
            return {"recorded": True}

    @app.post("/api/groups/{group_id}/close")
    def close(group_id: str, authorization: str | None = Header(default=None)):
        with db.transaction() as connection:
            group = room(connection, group_id)
            who = member(connection, group_id, authorization)
            owner(group, who)
            if group["phase"] != "voting":
                raise HTTPException(409, "There is no open vote")
            finalise(connection, group_id)
            return {"closed": True}

    @app.post("/api/groups/{group_id}/reset")
    def reset(group_id: str, authorization: str | None = Header(default=None)):
        with db.transaction() as connection:
            group = room(connection, group_id)
            who = member(connection, group_id, authorization)
            owner(group, who)
            connection.execute("DELETE FROM votes WHERE group_id=?", (group_id,))
            connection.execute("UPDATE groups SET phase='collecting',recommendations='[]',winner=NULL WHERE id=?", (group_id,))
            return {"reset": True}

    @app.delete("/api/groups/{group_id}")
    def delete_group(group_id: str, authorization: str | None = Header(default=None)):
        with db.transaction() as connection:
            group = room(connection, group_id)
            who = member(connection, group_id, authorization)
            owner(group, who)
            connection.execute("DELETE FROM groups WHERE id=?", (group_id,))
        with db.connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"deleted": True}

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/g/{group_id}", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "static/index.html")

    return app
