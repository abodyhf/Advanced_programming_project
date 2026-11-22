"""RDFLib builds RDF, pySHACL validates it, Oxigraph executes SPARQL."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote
from pyoxigraph import Store, RdfFormat
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
        self.store.bulk_load(input=graph.serialize(format="turtle"), format=RdfFormat.TURTLE)
        self.node_ids = {str(iri(key)): key for key in self.entities}
        self.fingerprint = hashlib.sha256(self.catalog_path.read_bytes()).hexdigest()[:12]

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
        """
        if not tastes:
            return {}
        if any(taste not in self.entities for taste in tastes):
            raise ValueError("Unknown taste identifier")
        values = " ".join(iri(taste).n3() for taste in tastes)
        similar = """UNION {
          ?taste a wt:Film .
          { ?taste wt:hasGenre/wt:subGenreOf* ?genre . ?film wt:hasGenre/wt:subGenreOf* ?genre }
          UNION { ?taste wt:directedBy ?person . ?film wt:directedBy ?person }
          UNION { ?taste wt:hasCast ?person . ?film wt:hasCast ?person }
        }""" if expand_films else ""
        query = f"""PREFIX wt: <{WT}>
        SELECT DISTINCT ?film ?taste WHERE {{
          VALUES ?taste {{ {values} }}
          ?film a wt:Film .
          {{ ?taste a wt:Film . BIND(?taste AS ?film) }}
          UNION {{ ?film wt:hasGenre/wt:subGenreOf* ?taste }}
          UNION {{ ?film (wt:directedBy|wt:hasCast) ?taste }}
          {similar}
        }}"""
        result = {}
        for row in self.store.query(query):
            film_id, taste_id = self.node_ids[row["film"].value], self.node_ids[row["taste"].value]
            result.setdefault(film_id, set()).add(taste_id)
        return result
