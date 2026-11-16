from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from watchtogether.api import create_app

@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as test_client:
        yield test_client

def auth(person):
    return {"Authorization": "Bearer " + person["token"]}

def make_group(client, count=2, likes=None, dislikes=None):
    creator = client.post('/api/groups', json={"title":"Friday night", "nickname":"Deniz"}).json()
    group_id = creator['group_id']
    people = [creator]
    for number in range(1, count):
        people.append(client.post(f'/api/groups/{group_id}/members', json={"nickname":f"Friend {number}"}).json())
    for person in people:
        response = client.put(f'/api/groups/{group_id}/profile', headers=auth(person), json={
            "likes": likes or ['genre:comedy','genre:adventure','genre:drama'],
            "dislikes": [] if dislikes is None else dislikes})
        assert response.status_code == 200, response.text
    return group_id, people

def start(client, group_id, people):
    result = client.post(f'/api/groups/{group_id}/recommendations', headers=auth(people[0]))
    assert result.status_code == 200, result.text
    return result.json()['recommendations']
