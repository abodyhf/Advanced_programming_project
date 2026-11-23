import json
import httpx
import pytest
from watchtogether import import_wikidata as importer
from watchtogether import validate_catalog
from watchtogether.graph import GraphStore

def rows():
    result=[]
    for property_id,value,label in [('P57','http://www.wikidata.org/entity/Q2','A Director'),('P161','http://www.wikidata.org/entity/Q3','An Actor'),('P136','http://www.wikidata.org/entity/Q4','comedy film'),('P577','2001-03-02T00:00:00Z','2001-03-02')]:
        result.append({'film':{'value':'http://www.wikidata.org/entity/Q1'},'filmLabel':{'value':'Test Film'},'property':{'value':'http://www.wikidata.org/prop/direct/'+property_id},'value':{'value':value},'valueLabel':{'value':label}})
    return result

def test_parse_wikidata_preserves_person_identifiers():
    film=importer.parse_films(rows())[0]
    assert film['title']=='Test Film' and film['year']==2001
    assert film['directors_ids']==['person:Q2'] and film['cast_ids']==['person:Q3']
    assert film['genres']==['comedy']
    assert importer.genre_key("Children's film")=='childrens' and importer.genre_key('Science fiction film')=='science-fiction'

def test_import_skips_incomplete_films():
    assert importer.parse_films(rows()[:-1])==[]

def test_retry_after_is_respected(monkeypatch):
    waits=[];calls=[]
    monkeypatch.setattr(importer.time,'sleep',waits.append)
    def handler(request):
        calls.append(request)
        return httpx.Response(429,headers={'Retry-After':'2'}) if len(calls)==1 else httpx.Response(200,json={'results':{'bindings':[]}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert importer.select(client,'SELECT * WHERE {}')==[]
    assert waits==[2] and len(calls)==2

def test_truncated_answer_is_retried(monkeypatch):
    monkeypatch.setattr(importer.time,'sleep',lambda seconds:None)
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,text='{"results": {"bindings": [{"film"') if len(calls)==1 else httpx.Response(200,json={'results':{'bindings':[]}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert importer.select(client,'SELECT * WHERE {}')==[]
    assert len(calls)==2

def test_forbidden_response_fails_without_retry():
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(403))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            importer.select(client,'SELECT * WHERE {}')

def test_import_saves_reloadable_shacl_valid_catalogue(tmp_path,monkeypatch):
    def select(client,query):
        return [{'film':{'value':'http://www.wikidata.org/entity/Q1'}}] if 'OFFSET' in query else rows()
    monkeypatch.setattr(importer,'select',select)
    output=importer.import_catalog(limit=1,batch_size=1,output=tmp_path/'wikidata.json')
    payload=json.loads(output.read_text())
    assert len(payload['films'])==1 and payload['_import']['offset']==1
    graph=GraphStore(output)
    assert graph.search('A Director','director')[0]['id']=='person:Q2'
    assert output.with_suffix('.ttl').exists()

def film_rows(number):
    return [{**row,'film':{'value':f'http://www.wikidata.org/entity/Q{number}'},'filmLabel':{'value':f'Film {number}'}} for row in rows()]

def test_interrupted_import_resumes_from_saved_offset(tmp_path,monkeypatch):
    monkeypatch.setattr(importer.time,'sleep',lambda seconds:None)
    offsets=[];fail_on={30}
    def select(client,query):
        if 'OFFSET' in query:
            assert 'ORDER BY' not in query  # Sorting all films times out on the live service.
            offset=int(query.rsplit('OFFSET',1)[1]);offsets.append(offset)
            return [{'film':{'value':f'http://www.wikidata.org/entity/Q{number}'}} for number in range(offset+10,min(offset+12,16))]
        if any(f'wd:Q{number} ' in query+' ' for number in fail_on):
            raise httpx.ConnectError('connection dropped')
        return [row for number in range(10,16) if f'wd:Q{number}' in query for row in film_rows(number)]
    monkeypatch.setattr(importer,'select',select)
    output=tmp_path/'wikidata.json'
    fail_on.add(12)  # The second batch (Q12, Q13) dies mid-download.
    with pytest.raises(httpx.ConnectError):
        importer.import_catalog(limit=6,batch_size=2,output=output)
    saved=json.loads(output.read_text())
    assert [film['id'] for film in saved['films']]==['film:Q10','film:Q11'] and saved['_import']['offset']==2
    assert not output.with_suffix('.json.tmp').exists()
    fail_on.discard(12);offsets.clear()
    importer.import_catalog(limit=6,batch_size=2,output=output)
    assert offsets==[2,4]  # Nothing already saved is downloaded again.
    films=json.loads(output.read_text())['films']
    assert [film['id'] for film in films]==[f'film:Q{number}' for number in range(10,16)]
    assert validate_catalog.check_records(films)=={}

def test_record_checks_report_duplicates_and_missing_fields():
    good=importer.parse_films(rows())[0]
    assert validate_catalog.check_records([good])=={}
    broken={**good,'title':' ','year':None,'genres':[],'directors':[],'cast':['']}
    problems=validate_catalog.check_records([good,good,broken])
    assert problems['duplicate id']==['film:Q1']*3
    for name in ['missing title','missing year','missing genres','missing directors','blank entry in actors']:
        assert problems[name]==['film:Q1'], name

def test_record_checks_reject_pictures_the_app_cannot_show():
    good=importer.parse_films(rows())[0]
    for url in ['https://image.tmdb.org/t/p/w342/abc.jpg','https://commons.wikimedia.org/wiki/Special:FilePath/A.jpg?width=400']:
        assert validate_catalog.check_records([{**good,'image':url}])=={}, url
    for url in ['http://image.tmdb.org/t/p/w342/abc.jpg','https://example.com/poster.jpg','https://image.tmdb.org/',
                'javascript:alert(1)','https://image.tmdb.org/a b.jpg',None]:
        assert validate_catalog.check_records([{**good,'image':url}])=={'invalid picture address':['film:Q1']}, url

def test_user_agent_carries_contact_and_403_is_explained():
    agent=importer.build_user_agent('https://example.org/me')
    assert agent.startswith('WatchTogether/1.0 (https://example.org/me;') and 'httpx/' in agent
    with pytest.raises(ValueError):
        importer.build_user_agent('  ')
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(403,text='robot policy'))) as client:
        with pytest.raises(httpx.HTTPStatusError,match=importer.CONTACT_ENV):
            importer.select(client,'SELECT * WHERE {}')

def test_images_are_added_resumably_and_reach_search_results(tmp_path,monkeypatch):
    from watchtogether import add_images
    monkeypatch.setattr(add_images.time,'sleep',lambda seconds:None)
    monkeypatch.setattr(importer,'select',lambda client,query:[{'film':{'value':'http://www.wikidata.org/entity/Q1'}}] if 'OFFSET' in query else rows())
    output=importer.import_catalog(limit=1,batch_size=1,output=tmp_path/'wikidata.json')
    catalog=json.loads(output.read_text())
    asked=[]
    def select(client,query):
        asked.append(query)
        return [{'film':{'value':'http://www.wikidata.org/entity/Q1'},'tmdb':{'value':'603'},
                 'image':{'value':'http://commons.wikimedia.org/wiki/Special:FilePath/A%20poster.jpg'}}]
    monkeypatch.setattr(add_images,'select',select)
    add_images.add_wikidata_images(catalog,output,client=None)
    add_images.add_wikidata_images(catalog,output,client=None)
    assert len(asked)==1  # Already-checked films are not asked for again.
    film=json.loads(output.read_text())['films'][0]
    assert film['image']=='https://commons.wikimedia.org/wiki/Special:FilePath/A%20poster.jpg?width=400' and film['tmdb_id']=='603'
    assert add_images.commons_url('http://commons.wikimedia.org/wiki/Special:FilePath/Trailer.webm') is None
    def tmdb(request):
        assert request.headers['authorization']=='Bearer test-token' and 'test-token' not in str(request.url)
        return httpx.Response(200,json={'poster_path':'/abc123.jpg'})
    add_images.add_tmdb_posters(catalog,output,'test-token',transport=httpx.MockTransport(tmdb))
    assert json.loads(output.read_text())['films'][0]['image']=='https://image.tmdb.org/t/p/w342/abc123.jpg'
    assert GraphStore(output).search('Test Film','film')[0]['image'].startswith('https://image.tmdb.org/')
    assert validate_catalog.check_records(catalog['films'])=={}

def test_importer_will_not_overwrite_unknown_file(tmp_path):
    output=tmp_path/'something.json'
    output.write_text('{"films": []}')
    with pytest.raises(ValueError,match='not created by this importer'):
        importer.import_catalog(limit=1,output=output)
