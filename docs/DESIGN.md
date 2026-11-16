# Design and proposal mapping

Python owns all business behavior. The browser is a small, buildless client that calls FastAPI and polls group state every three seconds while the tab is visible.

The film JSON file is durable source data. RDFLib maps it to the project's OWL vocabulary and schema.org Movie types. Film records require a title, year, genre, director and cast member in SHACL. Oxigraph holds the query index. SPARQL expands preferences through director, cast and genre links, including the configured subgenre path. Ranking combines minimum and average member coverage to favor agreement.

Room membership, round state and votes live in SQLite. A saved profile contains both preference identifier arrays and its SHACL-validated RDF Turtle serialization. This avoids requiring users to install a separate graph database server, and ensures membership/round/vote updates are transactional. The query index is not the authoritative store for user profiles, and it is rebuilt at startup.

The OWL ontology supplies domain classes and relationships. This version does not use owlready2 or claim full OWL reasoning. The actual graph behavior is explicit and covered by tests. It also does not use SPARQLWrapper: Python httpx sends standard SPARQL JSON requests to Wikidata. These substitutions keep dependencies focused while preserving the proposal's central RDF, SPARQL, Oxigraph, SHACL and Python behavior.

There are three visible room stages: entering tastes, the shortlist/vote, and the final pick. The organiser can begin a new round to edit tastes or admit late members. Because there is no identity verification, random membership credentials rather than nickname text authorize all actions.

The included 80-film dataset supports demonstration and automated tests. A resumable importer supports the planned expansion; it does not prove the proposal's quantitative dataset or satisfaction goals have been met. Those need real import and user-study evidence.

The generated code does not include the proposal's team roster or student contact details, and it does not imply that any teammate reviewed or released this implementation.
