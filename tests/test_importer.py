import json
import httpx
import pytest
from watchtogether import import_wikidata as importer
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

def test_forbidden_response_fails_without_retry():
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(403))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            importer.select(client,'SELECT * WHERE {}')

def test_import_saves_reloadable_shacl_valid_catalogue(tmp_path,monkeypatch):
    def select(client,query):
        return [{'film':{'value':'http://www.wikidata.org/entity/Q1'}}] if 'SELECT DISTINCT' in query else rows()
    monkeypatch.setattr(importer,'select',select)
    output=importer.import_catalog(limit=1,batch_size=1,output=tmp_path/'wikidata.json')
    payload=json.loads(output.read_text())
    assert len(payload['films'])==1 and payload['_import']['offset']==1
    graph=GraphStore(output)
    assert graph.search('A Director','director')[0]['id']=='person:Q2'
    assert output.with_suffix('.ttl').exists()

def test_importer_will_not_overwrite_unknown_file(tmp_path):
    output=tmp_path/'something.json'
    output.write_text('{"films": []}')
    with pytest.raises(ValueError,match='not created by this importer'):
        importer.import_catalog(limit=1,output=output)
