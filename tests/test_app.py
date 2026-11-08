import random
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('BBS_AUDIO_CACHE',str(tmp_path/'audio-cache'))
    monkeypatch.setenv('BBS_MODEL_DIR',str(tmp_path/'models'))
    monkeypatch.setattr(main, 'DB', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(main, 'SAMPLE', True)
    monkeypatch.setattr(main, 'CATALOG', False)
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


def test_shuffle(client):
    body = {'creature_ids': list(range(1, 9)), 'shuffle': True, 'seed': 42}
    result = client.post('/api/tournament', json=body).json()
    again = client.post('/api/tournament', json=body).json()
    assert result == again
    ids = [c['id'] for m in result['rounds'][0]['matches'] for c in [m['left'],m['right']]]
    assert sorted(ids) == list(range(1,9))
    assert ids != list(range(1,9))


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


def test_catalog_preserves_existing_creatures(client, monkeypatch):
    monkeypatch.setattr(main, 'SAMPLE', False)
    monkeypatch.setattr(main, 'CATALOG', True)
    with sqlite3.connect(main.DB) as conn:
        conn.execute("UPDATE creatures SET description='Parent custom profile', pronunciation='Custom guide' WHERE id=1")
    main.initialize_database()
    first = client.get('/api/creatures').json()
    main.initialize_database()
    second = client.get('/api/creatures').json()
    assert first == second
    assert len(first) == 164
    assert len([r for r in first if r['category']=='dinosaur']) >= 100
    assert len([r for r in first if r['category']=='shark']) >= 40
    assert next(r for r in first if r['id']==1)['description']=='Parent custom profile'
    assert next(r for r in first if r['id']==1)['pronunciation']=='Custom guide'
    assert all(r['length_m'] is None for r in first)
    assert client.get('/api/selection/random?category=ocean').status_code == 200


def test_complete_adventure_and_reload(client):
    body={'creature_ids':list(range(1,9)), 'seed':123, 'duration':'short','realism':'balanced'}
    initial=client.post('/api/tournament',json=body).json()
    assert initial['completed']==0 and initial['champion'] is None
    assert initial['chapter']['generated_by']=='local_template'
    assert all(m['winner'] is None for r in initial['rounds'] for m in r['matches'])
    for completed in range(8):
        body['completed']=completed
        state=client.post('/api/adventure',json=body).json()
        assert sum(m['status']=='complete' for r in state['rounds'] for m in r['matches'])==completed
        assert client.post('/api/adventure',json=body).json()==state
        if completed<7:
            assert state['chapter']
            assert 'winner' not in state['chapter']
        else:
            assert state['chapter'] is None
            assert state['champion']['id'] in body['creature_ids']
            assert state['rounds'][2]['matches'][0]['winner']==state['champion']
            for ri in [1,2]:
                for m in state['rounds'][ri]['matches']:
                    assert m['left'] and m['right']


@pytest.mark.parametrize('field,value', [('completed',-1),('completed',8),('completed',True),('seed',-1),('seed',2**32),('seed','bad')])
def test_adventure_validation(client,field,value):
    body={'creature_ids':list(range(1,9)), 'seed':123,field:value}
    assert client.post('/api/adventure',json=body).status_code==422


def test_chapter_lengths(client):
    counts=[]
    for duration in ['short','normal','long']:
        state=client.post('/api/tournament',json={'creature_ids':list(range(1,9)),'seed':1,'duration':duration}).json()
        counts.append(len(' '.join(state['chapter']['paragraphs']).split()))
    assert 100<=counts[0]<counts[1]<counts[2]


def test_seeded_rules_are_reproducible():
    from app.adventure import winner_for, UPSET_CHANCE
    a={'id':1,'name':'Tyrannosaurus'}
    b={'id':2,'name':'Microraptor'}
    assert UPSET_CHANCE['realistic']<UPSET_CHANCE['balanced']<UPSET_CHANCE['anything']
    for mode in UPSET_CHANCE:
        assert winner_for(a,b,42,'r0m0',mode)==winner_for(a,b,42,'r0m0',mode)
    # Across fixed seeds, fantasy gives the outsider more wins than realistic mode.
    wins={mode:sum(winner_for(a,b,s,'r0m0',mode)==b for s in range(1000)) for mode in UPSET_CHANCE}
    assert wins['realistic']<wins['balanced']<wins['anything']


def test_fresh_catalog_has_guides_and_provenance(client,monkeypatch,tmp_path):
    monkeypatch.setattr(main,'SAMPLE',False)
    monkeypatch.setattr(main,'CATALOG',True)
    monkeypatch.setattr(main,'DB',tmp_path/'catalog.sqlite3')
    rows=client.get('/api/creatures').json()
    assert len(rows)==164
    assert len({r['catalog_key'] for r in rows})==164
    assert all(r['pronunciation'] and r['source_url'].startswith('https://') for r in rows)
    assert all(r['review_status']=='reference_check_pending' for r in rows)


def test_v1_sample_pronunciation_upgrade(client):
    with sqlite3.connect(main.DB) as conn:
        conn.execute('UPDATE creatures SET pronunciation=NULL WHERE id=1')
    main.initialize_database()
    row=next(r for r in main.creatures() if r['id']==1)
    assert row['pronunciation']=='tie RAN oh SAWR us'
