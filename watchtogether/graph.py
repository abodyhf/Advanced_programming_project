"""RDFLib builds RDF, pySHACL validates it, Oxigraph executes SPARQL."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote
from pyoxigraph import NamedNode, Quad, Store, RdfFormat
from pyshacl import validate
from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, URIRef

ROOT = Path(__file__).resolve().parents[1]
WT = Namespace("https://watchtogether.example/vocab/")
ENTITY = "https://watchtogether.example/entity/"
SCHEMA = Namespace("https://schema.org/")
PARENTS = {"anime": ["animation"], "heist": ["crime"],
           "romantic-comedy": ["romance", "comedy"],
           "psychological-thriller": ["thriller"], "superhero": ["action", "science-fiction"],
           # Imported Wikidata kinds whose name does not spell out the parent genre.
           "slasher": ["horror"], "zombie": ["horror"], "vampire": ["horror"], "werewolf": ["horror"],
           "splatter": ["horror"], "gore": ["horror"], "cannibal": ["horror"], "giallo": ["thriller"],
           "suspense": ["thriller"], "cyberpunk": ["science-fiction"], "postcyberpunk": ["cyberpunk"],
           "biopunk": ["science-fiction"], "steampunk": ["science-fiction"], "dieselpunk": ["science-fiction"],
           "dystopian": ["science-fiction"], "post-apocalyptic": ["science-fiction"],
           "alien-invasion": ["science-fiction"], "time-travel": ["science-fiction"],
           "space-opera": ["science-fiction"], "tech-noir": ["science-fiction"], "retrofuturism": ["science-fiction"],
           "slapstick": ["comedy"], "parody": ["comedy"], "mockumentary": ["comedy"], "farce": ["comedy"],
           "satire": ["comedy"], "satirical": ["comedy"], "tragicomedy": ["comedy", "drama"],
           "melodrama": ["drama"], "docudrama": ["drama"], "martial-arts": ["action"], "kung-fu": ["martial-arts"],
           "wuxia": ["martial-arts"], "ninja": ["martial-arts"], "bruceploitation": ["martial-arts", "exploitation"],
           "girls-with-guns": ["action"], "gangster": ["crime"], "yakuza": ["gangster"], "poliziotteschi": ["crime"],
           "film-noir": ["crime"], "neo-noir": ["film-noir"], "sword-and-sorcery": ["fantasy"],
           "cinematic-fairy-tale": ["fantasy"], "rockumentary": ["music-documentary"], "partisan": ["war"],
           "comedy-porn": ["pornographic"], "erotica": ["erotic"], "sexploitation": ["exploitation"],
           "nunsploitation": ["exploitation"], "blaxploitation": ["exploitation"]}
# A compound name is a kind of each genre spelled inside it: "comedy-horror" is comedy and
# horror, "spaghetti-western" is a western. These words do not count:
WORD_ALIASES = {"romantic": "romance", "porn": "pornographic"}
NEVER_PARENT = {"fiction"}  # "science-fiction" films are not the vague "fiction" tag
NOT_PARENTS = {("live-action-animated", "action"), ("pseudo-documentary", "documentary")}
KNOWN_GENRES = set(PARENTS) | {parent for parents in PARENTS.values() for parent in parents}


def genre_parents(genres):
    """child -> parents for the genres a catalogue uses (and the parents they reach)."""
    used, parents = set(genres), {}
    todo = sorted(used)
    while todo:
        genre = todo.pop(0)
        words = [WORD_ALIASES.get(word, word) for word in genre.split("-")]
        found = list(PARENTS.get(genre, []))
        for size in range(len(words) - 1, 0, -1):
            for start in range(len(words) - size + 1):
                found.append("-".join(words[start:start + size]))
        found = [parent for parent in dict.fromkeys(found)
                 if parent != genre and parent not in NEVER_PARENT and (genre, parent) not in NOT_PARENTS
                 and (parent in used or parent in KNOWN_GENRES)]
        if found:
            parents[genre] = found
        for parent in found:
            if parent not in used:  # a known genre no film is tagged with directly
                used.add(parent)
                todo.append(parent)
    return parents

def slug(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")

def iri(entity_id):
    return URIRef(ENTITY + quote(entity_id, safe=":-"))

def label_genre(value):
    return value.replace("-", " ").title().replace("Science Fiction", "Science fiction")

class GraphStore:
    def __init__(self, catalog_path=None):
        self.catalog_path = Path(catalog_path or ROOT / "data/catalog.json")
        catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.source = catalog["source"]
        self.movies = {film["id"]: film for film in catalog["films"]}
        if len(self.movies) != len(catalog["films"]):
            raise ValueError("Catalogue contains duplicate film identifiers")
        self.entities = {}
        graph = Graph().parse(ROOT / "data/ontology.ttl", format="turtle")
        graph.bind("wt", WT)
        for film_id, film in self.movies.items():
            node = iri(film_id)
            graph.add((node, RDF.type, WT.Film))
            graph.add((node, RDF.type, SCHEMA.Movie))
            graph.add((node, WT.title, Literal(film["title"])))
            graph.add((node, WT.year, Literal(int(film["year"]))))
            graph.add((node, SCHEMA.name, Literal(film["title"])))
            if re.fullmatch(r"film:Q\d+", film_id):
                graph.add((node, OWL.sameAs, URIRef("http://www.wikidata.org/entity/" + film_id[5:])))
            self.entities[film_id] = {"id": film_id, "label": film["title"], "kind": "film",
                                      "detail": f'{film["year"]} · {", ".join(film["directors"])}'}
            if str(film.get("image", "")).startswith("https://"):
                graph.add((node, SCHEMA.image, URIRef(film["image"])))
                self.entities[film_id]["image"] = film["image"]
            for genre in film["genres"]:
                genre_id = "genre:" + genre
                graph.add((node, WT.hasGenre, iri(genre_id)))
                graph.add((iri(genre_id), RDF.type, WT.Genre))
                self.entities[genre_id] = {"id": genre_id, "label": label_genre(genre), "kind": "genre", "detail": "Genre"}
            for field, relation, role in [("directors", WT.directedBy, "director"), ("cast", WT.hasCast, "actor")]:
                for index, name in enumerate(film[field]):
                    imported_ids = film.get(field + "_ids", [])
                    person_id = imported_ids[index] if imported_ids else "person:" + slug(name)
                    graph.add((node, relation, iri(person_id)))
                    graph.add((iri(person_id), RDF.type, WT.Person))
                    if re.fullmatch(r"person:Q\d+", person_id):
                        graph.add((iri(person_id), OWL.sameAs, URIRef("http://www.wikidata.org/entity/" + person_id[7:])))
                    entry = self.entities.setdefault(person_id, {"id": person_id, "label": name, "kind": "person", "roles": [], "detail": ""})
                    if role not in entry["roles"]:
                        entry["roles"].append(role)
                    entry["detail"] = " / ".join(entry["roles"]).title()
        self.genre_parents = genre_parents({genre for film in self.movies.values() for genre in film["genres"]})
        for child, parents in self.genre_parents.items():
            for parent in parents:
                graph.add((iri("genre:" + child), WT.subGenreOf, iri("genre:" + parent)))
                self.entities.setdefault("genre:" + parent, {"id": "genre:" + parent, "label": label_genre(parent), "kind": "genre", "detail": "Genre"})
        for entity_id, entity in self.entities.items():
            graph.add((iri(entity_id), RDFS.label, Literal(entity["label"])))
        self.shapes = Graph().parse(ROOT / "data/shapes.ttl", format="turtle")
        conforms, _, report = validate(graph, shacl_graph=self.shapes)
        if not conforms:
            raise ValueError("Invalid film catalogue:\n" + report)
        self.rdf = graph
        # The durable catalogue is JSON. Rebuilding this local index avoids stale/imported stores.
        self.store = Store()
        # N-Triples: rdflib writes it ~9x faster than Turtle (no prefix/qname work) on 10k films.
        self.store.bulk_load(input=graph.serialize(format="nt"), format=RdfFormat.N_TRIPLES)
        # Index-only inference: wt:inGenre = hasGenre/subGenreOf*, so queries need no property paths.
        in_genre = NamedNode(str(WT.inGenre))
        self.store.extend(Quad(NamedNode(str(iri(film_id))), in_genre, NamedNode(str(iri("genre:" + genre))))
                          for film_id, film in self.movies.items() for genre in self.film_genres(film_id))
        self.node_ids = {str(iri(key)): key for key in self.entities}
        self.term_ids = {NamedNode(node): key for node, key in self.node_ids.items()}  # skips .value per row
        self.fingerprint = hashlib.sha256(self.catalog_path.read_bytes()).hexdigest()[:12]

    def ancestors(self, genre):
        """The genre and every parent above it."""
        seen, todo = {genre}, [genre]
        while todo:
            for parent in self.genre_parents.get(todo.pop(), []):
                if parent not in seen:
                    seen.add(parent)
                    todo.append(parent)
        return seen

    def film_genres(self, film_id):
        """Genres a film belongs to, including every parent of its tagged genres."""
        return sorted({ancestor for genre in self.movies[film_id]["genres"] for ancestor in self.ancestors(genre)})

    def people(self, film_id, field):
        """Person identifiers for a film's "directors" or "cast", as used in the graph."""
        film = self.movies[film_id]
        return film.get(field + "_ids") or ["person:" + slug(name) for name in film[field]]

    def why(self, taste, film_id):
        """A short, checkable sentence saying how a liked entity reaches a film."""
        film, kind = self.movies[film_id], self.entities[taste]["kind"]
        if taste == film_id:
            return "this film"
        if kind == "genre":
            if taste[6:] in film["genres"]:
                return "genre"
            via = [self.entities["genre:" + tag]["label"] for tag in film["genres"] if taste[6:] in self.ancestors(tag)]
            return "via " + ", ".join(via)
        if kind == "person":
            directs, acts = taste in self.people(film_id, "directors"), taste in self.people(film_id, "cast")
            return "directs it and is in the cast" if directs and acts else "directs it" if directs else "in the cast"
        parts = []
        for field, heading in (("directors", "same director"), ("cast", "shared cast")):
            theirs = set(self.people(film_id, field))
            shared = [self.entities[person]["label"] for person in self.people(taste, field) if person in theirs]
            if shared:
                parts.append(f"{heading}: {', '.join(shared[:3])}")
        shared = set(self.film_genres(taste)) & set(self.film_genres(film_id))
        # Name the most specific shared genres: "Romantic Comedy", not also "Romance" and "Comedy".
        specific = sorted(genre for genre in shared
                          if not any(other != genre and genre in self.ancestors(other) for other in shared))
        if specific:
            parts.append("shared genre: " + ", ".join(self.entities["genre:" + genre]["label"] for genre in specific[:3]))
        return "; ".join(parts)

    def search(self, query="", kind="all", limit=24):
        query = query.casefold().strip()
        values = [v for v in self.entities.values()
                  if (query in v["label"].casefold()) and
                  (kind == "all" or v["kind"] == kind or kind in v.get("roles", []))]
        return sorted(values, key=lambda v: (not v["label"].casefold().startswith(query), v["label"].casefold()))[:limit]

    def make_profile(self, member_id, nickname, likes, dislikes):
        # Closed shape rejects accidental e-mail/real-name/other profile properties.
        graph = Graph()
        node = URIRef("urn:watchtogether:profile:" + member_id)
        graph.add((node, RDF.type, WT.TasteProfile))
        graph.add((node, WT.nickname, Literal(nickname)))
        for relation, values in [(WT.likes, likes), (WT.dislikes, dislikes)]:
            for value in values:
                graph.add((node, relation, iri(value)))
        conforms, _, report = validate(graph, shacl_graph=self.shapes)
        if not conforms:
            raise ValueError("Profile validation failed: " + report)
        return graph.serialize(format="turtle")

    def links_for(self, tastes, expand_films=True):
        """Return movie -> directly/indirectly matched input entities using SPARQL.

        Liked film: same film, shared director/cast/genre. Disliked film: that film
        only. Other dislikes exclude any film with the person or (sub)genre.
        All identifiers must be resolved locally before being rendered into VALUES.

        Two queries per call: what the liked films share, then the films of every
        distinct genre/person involved. Each genre is read once even when several
        tastes lead to it, which keeps big groups on a big catalogue fast.
        """
        if not tastes:
            return {}
        if any(taste not in self.entities for taste in tastes):
            raise ValueError("Unknown taste identifier")
        ids, prefix = self.term_ids, f"PREFIX wt: <{WT}>\n"
        relation = {NamedNode(str(WT.inGenre)): "genre", NamedNode(str(WT.directedBy)): "director",
                    NamedNode(str(WT.hasCast)): "cast"}
        # 1. What each liked film offers to share: its genres (with parents), directors and cast.
        shares = {}
        films = [taste for taste in tastes if taste in self.movies] if expand_films else []
        if films:
            # One branch per fixed predicate; a variable predicate made Oxigraph scan every triple.
            branches = " UNION ".join(f"{{ ?taste {name} ?shared BIND({name} AS ?relation) }}"
                                      for name in ("wt:inGenre", "wt:directedBy", "wt:hasCast"))
            query = prefix + f"""SELECT ?taste ?relation ?shared WHERE {{
              VALUES ?taste {{ {" ".join(iri(film).n3() for film in films)} }} {branches} }}"""
            for taste, link, shared in self.store.query(query):
                shares.setdefault(ids[taste], []).append((relation[link], ids[shared]))
        # 2. One lookup per distinct genre/person for the whole request, however many tastes need it.
        wanted = {(kind, entity) for pairs in shares.values() for kind, entity in pairs}
        for taste in tastes:
            kind = self.entities[taste]["kind"]
            if kind == "genre":
                wanted.add(("genre", taste))
            elif kind == "person":
                wanted.update({("director", taste), ("cast", taste)})
        reach = {key: set() for key in wanted}
        if wanted:
            branches = []
            for kind, name in (("genre", "wt:inGenre"), ("director", "wt:directedBy"), ("cast", "wt:hasCast")):
                entities = " ".join(iri(entity).n3() for wanted_kind, entity in sorted(wanted) if wanted_kind == kind)
                if entities:
                    branches.append(f"{{ VALUES ?entity {{ {entities} }} ?film {name} ?entity BIND({name} AS ?relation) }}")
            query = prefix + f"SELECT ?relation ?entity ?film WHERE {{ {' UNION '.join(branches)} }}"
            for link, entity, film in self.store.query(query):
                reach[relation[link], ids[entity]].add(ids[film])
        # 3. Combine: a liked film reaches itself and everything sharing one of its features.
        result = {}
        for taste in tastes:
            kind = self.entities[taste]["kind"]
            if kind == "film":
                films_reached = {taste}.union(*(reach[key] for key in shares.get(taste, [])))
            elif kind == "genre":
                films_reached = reach["genre", taste]
            else:
                films_reached = reach["director", taste] | reach["cast", taste]
            for film in films_reached:
                result.setdefault(film, set()).add(taste)
        return result
