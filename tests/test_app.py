import random
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(main, 'SAMPLE', True)
    with TestClient(main.app) as c:
        yield c


def test_initialization(client):
    assert main.DB.exists()
    main.initialize_database()
    with sqlite3.connect(main.DB) as conn:
        assert conn.execute('SELECT count(*) FROM creatures').fetchone()[0] == 24
    assert client.get('/').status_code == 200
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/api/config').json()['sample_data']


@pytest.mark.parametrize('category', ['dinosaur', 'shark', 'marine_reptile'])
def test_category_search(client, category):
    rows = client.get('/api/creatures', params={'category': category}).json()
    assert len(rows) == 8
    assert all(r['category'] == category for r in rows)
    assert client.get('/api/creatures', params={'q': rows[0]['scientific_name'].upper()}).json() == [rows[0]]
    assert client.get('/api/creatures?q=%27%20OR%201=1').json() == []


def test_empty_library(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'SAMPLE', False)
    monkeypatch.setattr(main, 'DB', tmp_path / 'empty.sqlite3')
    assert client.get('/api/creatures').json() == []
    assert client.get('/api/selection/random?category=dinosaur').status_code == 422


def test_random_uses_sample_without_replacement(client, monkeypatch):
    calls = []
    original = random.sample
    def sample(rows, count):
        calls.append(count)
        return original(rows, count)
    monkeypatch.setattr(main.random, 'sample', sample)
    for category in ['dinosaur', 'shark', 'marine_reptile']:
        ids = client.get('/api/selection/random', params={'category': category}).json()['creature_ids']
        assert len(set(ids)) == 8
        assert set(ids) == {r['id'] for r in main.creatures(category)}
    assert calls == [8, 8, 8]


def test_bracket_order_and_sources(client):
    ids = [8, 7, 6, 5, 4, 3, 2, 1]
    result = client.post('/api/tournament', json={'creature_ids': ids}).json()
    assert [len(r['matches']) for r in result['rounds']] == [4, 2, 1]
    assert [c['id'] for m in result['rounds'][0]['matches'] for c in [m['left'], m['right']]] == ids
    assert result['rounds'][1]['matches'][0]['sources'] == ['r0m0', 'r0m1']
    assert all(m['winner'] is None for r in result['rounds'] for m in r['matches'])
    assert result['realism'] == 'balanced' and result['duration'] == 'normal'


def test_shuffle(client, monkeypatch):
    monkeypatch.setattr(main.random, 'shuffle', lambda rows: rows.reverse())
    result = client.post('/api/tournament', json={'creature_ids': list(range(1, 9)), 'shuffle': True}).json()
    assert result['rounds'][0]['matches'][0]['left']['id'] == 8


@pytest.mark.parametrize('ids', [[1, 2], [1]*8, list(range(90,98)), ['1']+list(range(2,9)), [True]+list(range(2,9))])
def test_invalid_selection(client, ids):
    assert client.post('/api/tournament', json={'creature_ids': ids}).status_code == 422


@pytest.mark.parametrize('field,value', [('realism','bad'),('duration','bad'),('extra',1)])
def test_invalid_settings(client, field, value):
    assert client.post('/api/tournament', json={'creature_ids': list(range(1,9)), field: value}).status_code == 422


@pytest.mark.parametrize('realism', ['realistic','balanced','anything'])
@pytest.mark.parametrize('duration', ['short','normal','long'])
def test_settings(client, realism, duration):
    assert client.post('/api/tournament', json={'creature_ids': list(range(1,9)), 'realism':realism,'duration':duration}).status_code == 200


def test_habitats(client):
    assert client.post('/api/tournament', json={'creature_ids':[9,10,11,12,17,18,19,20]}).status_code == 200
    assert client.post('/api/tournament', json={'creature_ids':[1,2,3,4,9,10,11,12]}).status_code == 422
    assert main.arenas_for([{'habitat':'semi_aquatic'},{'habitat':'marine'}]) == {'water'}
    assert main.arenas_for([{'habitat':'semi_aquatic'},{'habitat':'land'}]) == {'land'}
    assert main.arenas_for([{'habitat':'unknown'}]) == set()


def test_invalid_requests(client):
    assert client.get('/api/creatures?category=invalid').status_code == 422
    assert client.get('/api/selection/random').status_code == 422
    assert client.post('/api/tournament', content='bad', headers={'Content-Type':'application/json'}).status_code == 422
