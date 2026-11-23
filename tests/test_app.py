import json
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from rdflib import Graph, Literal, Namespace, RDF, URIRef
from pyshacl import validate
from watchtogether.graph import WT, ROOT, iri
from conftest import auth, make_group, start

def test_home_serves_local_assets_and_csp(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'WatchTogether' in response.text
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/static/styles.css').status_code == 200

def test_script_is_served_as_javascript(client):
    # With nosniff, a text/plain app.js (the Windows registry default) is never executed.
    assert 'javascript' in client.get('/static/app.js').headers['content-type']
    assert client.get('/static/styles.css').headers['content-type'].startswith('text/css')

def test_catalogue_search_pages_without_gaps_or_repeats(client):
    first = client.get('/api/catalog', params={'q':'','kind':'film'}).json()
    assert len(first['items']) == 24 and first['has_more'] is True
    seen = [item['id'] for item in first['items']]
    offset = 24
    while True:
        page = client.get('/api/catalog', params={'q':'','kind':'film','offset':offset}).json()
        seen += [item['id'] for item in page['items']]
        offset += 24
        if not page['has_more']:
            break
    assert len(seen) == len(set(seen)) == 80
    assert client.get('/api/catalog', params={'q':'','kind':'film','offset':80}).json() == {**page, 'items': [], 'has_more': False}
    assert client.get('/api/catalog', params={'limit':101}).status_code == 422

def test_health_reports_actual_catalogue(client):
    health = client.get('/api/health').json()
    assert health['films'] == 80
    assert 'Hand-curated' in health['catalogue_source']

@pytest.mark.parametrize('query,kind,expected', [('incep','film','Inception'),('nolan','director','Christopher Nolan'),('tom hanks','actor','Tom Hanks'),('comedy','genre','Comedy')])
def test_search_finds_films_genres_and_people(client, query, kind, expected):
    data = client.get('/api/catalog', params={'q':query,'kind':kind}).json()
    assert any(item['label'] == expected for item in data['items'])

def test_search_does_not_interpolate_sparql(client):
    assert client.get('/api/catalog', params={'q':'" } UNION { ?a ?b ?c'}).json()['items'] == []

@pytest.mark.parametrize('body',[{'title':'','nickname':'A'},{'title':'x','nickname':'   '},{'title':'x','nickname':'a'*25},{'title':'x','nickname':'a\nb'}])
def test_invalid_group_names_are_rejected(client,body):
    assert client.post('/api/groups',json=body).status_code == 422

def test_invite_is_public_but_profiles_and_tokens_are_private(client):
    gid, people = make_group(client)
    public = client.get(f'/api/groups/{gid}').json()
    assert public['member_count'] == 2
    assert 'members' not in public and 'me' not in public and 'owner_id' not in public
    private = client.get(f'/api/groups/{gid}',headers=auth(people[0])).json()
    assert private['me']['ready']
    assert 'token' not in json.dumps(private) and 'token_hash' not in json.dumps(private)

def test_join_limit(client):
    gid, people = make_group(client,8)
    result = client.post(f'/api/groups/{gid}/members',json={'nickname':'Ninth'})
    assert result.status_code == 409 and 'full' in result.text

def test_concurrent_joins_never_exceed_eight(client):
    gid = client.post('/api/groups',json={'title':'Many friends','nickname':'Host'}).json()['group_id']
    def join(number):
        return client.post(f'/api/groups/{gid}/members',json={'nickname':f'Guest {number}'}).status_code
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(join,range(10)))
    assert results.count(201) == 7
    assert results.count(409) == 3
    assert client.get(f'/api/groups/{gid}').json()['member_count'] == 8

def test_duplicate_nickname_is_case_insensitive(client):
    gid, _ = make_group(client)
    assert client.post(f'/api/groups/{gid}/members',json={'nickname':' deniz '}).status_code == 409

def test_unknown_group_returns_404(client):
    assert client.get('/api/groups/not-a-real-room').status_code == 404

def test_profile_requires_membership(client):
    gid, people = make_group(client)
    assert client.put(f'/api/groups/{gid}/profile',json={'likes':[]}).status_code == 401

def test_token_is_scoped_to_its_group(client):
    gid, people = make_group(client)
    other, other_people = make_group(client)
    assert client.get(f'/api/groups/{gid}',headers=auth(other_people[0])).status_code == 401

@pytest.mark.parametrize('likes,dislikes',[
    ([],['genre:comedy','genre:horror','genre:adventure']),
    (['genre:comedy'],[]),
    (['genre:comedy','genre:comedy','genre:drama'],[]),
    (['genre:comedy','genre:adventure','genre:drama'],['genre:comedy']),
    (['genre:comedy','genre:adventure','genre:unknown'],[]),
    (['genre:comedy','genre:adventure','> } UNION { ?x ?y ?z'],[]),
])
def test_invalid_taste_profiles_rejected(client,likes,dislikes):
    gid, people = make_group(client)
    result = client.put(f'/api/groups/{gid}/profile',headers=auth(people[0]),json={'likes':likes,'dislikes':dislikes})
    assert result.status_code == 422

def test_profile_persists_as_valid_rdf(client):
    gid, people = make_group(client)
    response = client.get(f'/api/groups/{gid}/profile.ttl',headers=auth(people[0]))
    graph = Graph().parse(data=response.text,format='turtle')
    profile = next(graph.subjects(RDF.type,WT.TasteProfile))
    assert len(list(graph.objects(profile,WT.likes))) == 3
    assert list(graph.objects(profile,WT.nickname)) == [Literal('Deniz')]
    assert validate(graph, shacl_graph=str(ROOT/'data/shapes.ttl'))[0]

def test_closed_shacl_shape_rejects_email(client):
    graph = Graph()
    node = URIRef('urn:profile:example')
    graph.add((node,RDF.type,WT.TasteProfile))
    graph.add((node,WT.nickname,Literal('Example')))
    graph.add((node,WT.likes,iri('genre:comedy')))
    graph.add((node,URIRef('https://schema.org/email'),Literal('not-real@example.test')))
    assert not validate(graph,shacl_graph=client.app.state.graph.shapes)[0]

def test_cannot_recommend_for_one_member(client):
    gid, people = make_group(client,1)
    assert client.post(f'/api/groups/{gid}/recommendations',headers=auth(people[0])).status_code == 409

def test_missing_profile_names_member(client):
    gid, people = make_group(client,1)
    client.post(f'/api/groups/{gid}/members',json={'nickname':'Missing friend'})
    result = client.post(f'/api/groups/{gid}/recommendations',headers=auth(people[0]))
    assert result.status_code == 409 and 'Missing friend' in result.text

def test_only_organiser_can_start(client):
    gid, people = make_group(client)
    assert client.post(f'/api/groups/{gid}/recommendations',headers=auth(people[1])).status_code == 403

def test_top_five_respect_dislikes_and_time_limit(client):
    gid, people = make_group(client,4,dislikes=['genre:horror'])
    before = time.perf_counter()
    movies = start(client,gid,people)
    assert time.perf_counter() - before < 5
    assert len(movies) == 5
    assert all('horror' not in movie['genres'] and len(movie['matches']) == 4 for movie in movies)
    assert all(match['because'] for movie in movies for match in movie['matches'])

def test_nonoverlapping_genres_can_find_shared_film(client):
    gid, people = make_group(client,2)
    for person,likes in zip(people,[['genre:comedy','genre:romance','genre:music'],['genre:science-fiction','genre:action','genre:thriller']]):
        client.put(f'/api/groups/{gid}/profile',headers=auth(person),json={'likes':likes,'dislikes':[]})
    movies = start(client,gid,people)
    assert all(len(movie['matches']) == 2 and all(match['because'] for match in movie['matches']) for movie in movies)

def test_no_common_film_is_explained(client):
    gid, people = make_group(client)
    all_genres = [entry['id'] for entry in client.app.state.graph.entities.values() if entry['kind']=='genre']
    # Keep one like and block every genre, without overlapping exact taste identifiers.
    client.put(f'/api/groups/{gid}/profile',headers=auth(people[0]),json={'likes':['person:tom-hanks'],'dislikes':all_genres})
    result = client.post(f'/api/groups/{gid}/recommendations',headers=auth(people[0]))
    assert result.status_code == 409 and 'No film matches' in result.text
    assert result.headers['X-Recommendation-Conflict'] == 'no_full_match'
    compromise = client.post(f'/api/groups/{gid}/recommendations?allow_compromise=true', headers=auth(people[0]))
    assert compromise.status_code == 409
    assert compromise.headers['X-Recommendation-Conflict'] == 'no_compromise'
    assert client.get(f'/api/groups/{gid}',headers=auth(people[0])).json()['phase'] == 'collecting'


def test_host_can_open_a_compromise_ballot_without_overriding_avoids(client):
    gid, (host, guest) = make_group(client)
    path = f'/api/groups/{gid}'
    assert client.put(path + '/profile', headers=auth(host), json={
        'likes': ['genre:anime', 'genre:family', 'person:hayao-miyazaki'], 'dislikes': ['genre:horror'],
    }).status_code == 200
    assert client.put(path + '/profile', headers=auth(guest), json={
        'likes': ['genre:horror', 'genre:thriller', 'person:jordan-peele'],
    }).status_code == 200

    assert client.post(path + '/recommendations', headers=auth(host)).status_code == 409
    assert client.get(path, headers=auth(host)).json()['phase'] == 'collecting'
    compromise = path + '/recommendations?allow_compromise=true'
    assert client.post(compromise, headers=auth(guest)).status_code == 403
    response = client.post(compromise, headers=auth(host))
    assert response.status_code == 200, response.text
    films = response.json()['recommendations']
    excluded = client.app.state.graph.links_for(['genre:horror'], expand_films=False)
    assert len(films) >= 2
    assert all(film['id'] not in excluded for film in films)
    assert all(sum(bool(match['because']) for match in film['matches']) == 1 for film in films)
    assert client.get(path, headers=auth(guest)).json()['recommendations'] == films

    for person, film in zip((host, guest), films):
        assert client.post(path + '/votes', headers=auth(person), json={'film_id': film['id']}).status_code == 201
    assert client.get(path, headers=auth(host)).json()['winner'] == films[0]['id']


def test_subgenre_matches_parent_and_parent_dislike(client):
    graph = client.app.state.graph
    animation = graph.links_for(['genre:animation'])
    assert any(graph.movies[film]['title']=='Spirited Away' for film in animation)
    thriller = graph.links_for(['genre:thriller'],expand_films=False)
    assert any(graph.movies[film]['title']=='Gone Girl' for film in thriller)

def test_film_dislike_excludes_only_that_film(client):
    graph = client.app.state.graph
    inception = next(key for key,value in graph.movies.items() if value['title']=='Inception')
    assert set(graph.links_for([inception],expand_films=False)) == {inception}
    assert len(graph.links_for([inception])) > 1

def test_person_preferences_follow_cast_and_director_edges(client):
    graph = client.app.state.graph
    linked = graph.links_for(['person:tom-hanks'],expand_films=False)
    assert any(graph.movies[film]['title']=='Toy Story' for film in linked)
    assert all('Tom Hanks' in graph.movies[film]['cast'] or 'Tom Hanks' in graph.movies[film]['directors'] for film in linked)

def test_profiles_and_members_freeze_during_voting(client):
    gid, people = make_group(client)
    start(client,gid,people)
    assert client.put(f'/api/groups/{gid}/profile',headers=auth(people[0]),json={'likes':['genre:comedy','genre:adventure','genre:drama']}).status_code == 409
    assert client.post(f'/api/groups/{gid}/members',json={'nickname':'Late friend'}).status_code == 409
    assert client.post(f'/api/groups/{gid}/recommendations',headers=auth(people[0])).status_code == 409

def test_outside_shortlist_vote_rejected(client):
    gid, people = make_group(client)
    start(client,gid,people)
    assert client.post(f'/api/groups/{gid}/votes',headers=auth(people[0]),json={'film_id':'film:outside'}).status_code == 422

def test_second_vote_rejected(client):
    gid, people = make_group(client,3)
    movies = start(client,gid,people)
    path = f'/api/groups/{gid}/votes'
    assert client.post(path,headers=auth(people[0]),json={'film_id':movies[0]['id']}).status_code == 201
    assert client.post(path,headers=auth(people[0]),json={'film_id':movies[1]['id']}).status_code == 409

def test_concurrent_duplicate_vote_records_once(client):
    gid, people = make_group(client,3)
    movies = start(client,gid,people)
    def cast(_):
        return client.post(f'/api/groups/{gid}/votes',headers=auth(people[0]),json={'film_id':movies[0]['id']}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(cast,range(2))) == [201,409]
    state = client.get(f'/api/groups/{gid}',headers=auth(people[0])).json()
    assert state['vote_count'] == 1

def test_majority_wins_and_last_vote_closes_round(client):
    gid, people = make_group(client,3)
    movies = start(client,gid,people)
    for person,index in zip(people,[1,1,0]):
        assert client.post(f'/api/groups/{gid}/votes',headers=auth(person),json={'film_id':movies[index]['id']}).status_code == 201
    state = client.get(f'/api/groups/{gid}',headers=auth(people[0])).json()
    assert state['phase']=='finished' and state['winner']==movies[1]['id']

def test_vote_tie_uses_higher_recommendation_score(client):
    gid, people = make_group(client,likes=['genre:comedy','genre:adventure','person:tom-hanks'])
    movies = start(client,gid,people)
    assert movies[0]['score'] > movies[-1]['score']
    for person,movie in zip(people,[movies[-1],movies[0]]):
        client.post(f'/api/groups/{gid}/votes',headers=auth(person),json={'film_id':movie['id']})
    state = client.get(f'/api/groups/{gid}',headers=auth(people[0])).json()
    assert state['winner']==movies[0]['id']

def test_owner_can_close_early_but_not_without_votes(client):
    gid, people = make_group(client,3)
    movies = start(client,gid,people)
    assert client.post(f'/api/groups/{gid}/close',headers=auth(people[0])).status_code == 409
    client.post(f'/api/groups/{gid}/votes',headers=auth(people[1]),json={'film_id':movies[0]['id']})
    assert client.post(f'/api/groups/{gid}/close',headers=auth(people[1])).status_code == 403
    assert client.post(f'/api/groups/{gid}/close',headers=auth(people[0])).status_code == 200
    assert client.get(f'/api/groups/{gid}',headers=auth(people[0])).json()['phase']=='finished'

def test_new_round_clears_votes_but_keeps_tastes(client):
    gid, people = make_group(client)
    movies = start(client,gid,people)
    client.post(f'/api/groups/{gid}/votes',headers=auth(people[0]),json={'film_id':movies[0]['id']})
    assert client.post(f'/api/groups/{gid}/reset',headers=auth(people[1])).status_code == 403
    assert client.post(f'/api/groups/{gid}/reset',headers=auth(people[0])).status_code == 200
    state=client.get(f'/api/groups/{gid}',headers=auth(people[0])).json()
    assert state['phase']=='collecting' and state['vote_count']==0 and not state['recommendations']
    assert all(person['ready'] for person in state['members'])

def test_state_survives_new_app_instance(client,tmp_path):
    from watchtogether.api import create_app
    from fastapi.testclient import TestClient
    gid,people = make_group(client)
    with TestClient(create_app(tmp_path)) as reopened:
        state=reopened.get(f'/api/groups/{gid}',headers=auth(people[0])).json()
        assert state['me']['nickname']=='Deniz' and state['me']['ready']

def test_filtered_shortlist_survives_restart(client, tmp_path):
    from fastapi.testclient import TestClient
    from watchtogether.api import create_app

    gid, people = make_group(client, likes=["film:inception-2010", "genre:comedy", "genre:drama"])
    group = f"/api/groups/{gid}"
    headers = auth(people[0])
    options = client.get("/api/catalog/filters").json()
    assert options["has_runtime"] and "English" in options["languages"]
    filters = {"min_year": 2010, "max_year": 2010, "max_runtime": 148, "language": "English"}
    endpoint = group + "/recommendations"
    assert client.post(endpoint, headers=auth(people[1]), json=filters).status_code == 403
    assert client.post(endpoint, headers=headers, json={**filters, "min_year": 2011}).status_code == 422
    assert client.post(endpoint, headers=headers, json={**filters, "max_runtime": 1}).status_code == 409

    response = client.post(endpoint + "?allow_compromise=true", headers=headers, json=filters)
    assert response.status_code == 200, response.text
    shortlist = response.json()["recommendations"]
    assert any(movie["id"] == "film:inception-2010" for movie in shortlist)
    for movie in shortlist:
        assert movie["year"] == 2010
        assert movie["runtime_minutes"] <= 148
        assert "English" in movie["languages"]

    with TestClient(create_app(tmp_path)) as reopened:
        state = reopened.get(group, headers=auth(people[1])).json()
        assert state["filters"] == filters
        assert reopened.post(group + "/reset", headers=headers).status_code == 200
        assert reopened.get(group, headers=headers).json()["filters"] == {}

def test_expired_room_cannot_be_revived_by_a_read(client):
    gid,people=make_group(client)
    with client.app.state.db.transaction() as connection:
        connection.execute('UPDATE groups SET last_used=? WHERE id=?',(time.time()-31*86400,gid))
    assert client.get(f'/api/groups/{gid}',headers=auth(people[0])).status_code==410

def test_cleanup_cascades_profiles_and_votes_and_preserves_active_groups(client):
    old,people=make_group(client)
    movies=start(client,old,people)
    client.post(f'/api/groups/{old}/votes',headers=auth(people[0]),json={'film_id':movies[0]['id']})
    active,_=make_group(client)
    now=time.time()
    with client.app.state.db.transaction() as connection:
        connection.execute('UPDATE groups SET last_used=? WHERE id=?',(now-31*86400,old))
    assert client.app.state.db.cleanup(now)==1
    with client.app.state.db.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM members WHERE group_id=?',(old,)).fetchone()[0]==0
        assert connection.execute('SELECT COUNT(*) FROM votes WHERE group_id=?',(old,)).fetchone()[0]==0
    assert client.get(f'/api/groups/{active}').status_code==200

def test_cleanup_boundary_is_thirty_days(client):
    gid,_=make_group(client)
    now=time.time()
    with client.app.state.db.transaction() as connection:
        connection.execute('UPDATE groups SET last_used=? WHERE id=?',(now-30*86400,gid))
    assert client.app.state.db.cleanup(now)==0
    assert client.app.state.db.cleanup(now+1)==1

def test_only_owner_can_delete_group(client):
    gid,people=make_group(client)
    assert client.delete(f'/api/groups/{gid}',headers=auth(people[1])).status_code==403
    assert client.delete(f'/api/groups/{gid}',headers=auth(people[0])).status_code==200
    assert client.get(f'/api/groups/{gid}').status_code==404

def test_demo_is_explicit_and_completes_with_one_real_vote(client):
    person=client.post('/api/demo').json()
    gid=person['group_id']
    state=client.get(f'/api/groups/{gid}',headers=auth(person)).json()
    assert state['is_demo'] and len(state['members'])==3
    movies=start(client,gid,[person])
    client.post(f'/api/groups/{gid}/votes',headers=auth(person),json={'film_id':movies[0]['id']})
    assert client.get(f'/api/groups/{gid}',headers=auth(person)).json()['phase']=='finished'

def test_catalogue_switch_invalidates_unavailable_tastes_and_round(client,tmp_path):
    from watchtogether.api import create_app
    from fastapi.testclient import TestClient
    gid,people=make_group(client,likes=['genre:comedy','genre:adventure','person:tom-hanks'])
    start(client,gid,people)
    payload=json.loads((ROOT/'data/catalog.json').read_text())
    for film in payload['films']:
        film['cast']=[name for name in film['cast'] if name!='Tom Hanks'] or ['Replacement Actor']
    changed=tmp_path/'changed-catalogue.json'
    changed.write_text(json.dumps(payload))
    with TestClient(create_app(tmp_path,catalog_path=changed)) as reopened:
        state=reopened.get(f'/api/groups/{gid}',headers=auth(people[0])).json()
        assert state['phase']=='collecting' and not state['recommendations']
        assert not state['me']['ready'] and 'person:tom-hanks' not in state['me']['likes']

def test_demo_works_with_a_small_imported_catalogue(tmp_path):
    from watchtogether.api import create_app
    from fastapi.testclient import TestClient
    payload=json.loads((ROOT/'data/catalog.json').read_text())
    payload['films']=payload['films'][:1]
    tiny=tmp_path/'tiny.json'
    tiny.write_text(json.dumps(payload))
    with TestClient(create_app(tmp_path,catalog_path=tiny)) as client:
        person=client.post('/api/demo').json()
        movies=start(client,person['group_id'],[person])
        assert len(movies)==1 and movies[0]['title']=='Inception'
