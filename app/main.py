from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import json
import os
import random
import sqlite3
import threading
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from app.adventure import progress
from app import library as encyclopedia
from app.library_routes import router as library_router
from app.admin_routes import router as admin_router, request_validation_error
from app.importer.auth import ParentAuth
from app.importer.store import root as importer_root
from app.audio.routes import router as audio_router, create_service

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get('BBS_DB_PATH', ROOT / 'data' / ('sample.sqlite3' if os.environ.get('BBS_SAMPLE_DATA') == '1' else 'creatures.sqlite3')))
SAMPLE = os.environ.get('BBS_SAMPLE_DATA') == '1'
CATALOG = os.environ.get('BBS_CATALOG', '1') == '1'
_database_ready = None
_database_lock = threading.RLock()
# A matchup needs a shared arena across every participant. Extend here as
# verified species gain more specific habitat requirements.
HABITAT_ARENAS = {'land': {'land'}, 'marine': {'water'},
                  'semi_aquatic': {'land', 'water'}}


def initialize_database():
    global _database_ready
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS creatures (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            scientific_name TEXT, category TEXT NOT NULL, habitat TEXT NOT NULL,
            length_m REAL, weight_kg REAL, diet TEXT, offense TEXT, defense TEXT,
            locomotion TEXT, description TEXT, image_reference TEXT, pronunciation TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS catalog_metadata (
            creature_id INTEGER PRIMARY KEY, metadata TEXT NOT NULL)''')
        if CATALOG and not SAMPLE:
            catalog = json.loads((ROOT / 'data' / 'catalog.json').read_text())
            for entry in catalog['creatures']:
                existing = conn.execute('SELECT id, category FROM creatures WHERE name = ?', (entry['name'],)).fetchone()
                if existing is None:
                    fields = ['name','scientific_name','category','habitat','diet','description','pronunciation']
                    cur = conn.execute(f"INSERT INTO creatures ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", [entry[k] for k in fields])
                    creature_id = cur.lastrowid
                    conn.execute('INSERT INTO catalog_metadata VALUES (?, ?)', (creature_id, json.dumps(entry)))
                elif existing[1] == entry['category']:
                    conn.execute("UPDATE creatures SET pronunciation=? WHERE id=? AND (pronunciation IS NULL OR pronunciation='')", (entry['pronunciation'], existing[0]))
        if SAMPLE:
            rows = json.loads((ROOT / 'data' / 'sample_creatures.json').read_text())
            for row in rows:
                keys = list(row)
                conn.execute(f"INSERT OR IGNORE INTO creatures ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", list(row.values()))
                conn.execute("UPDATE creatures SET pronunciation=? WHERE name=? AND scientific_name=? AND (pronunciation IS NULL OR pronunciation='')", (row['pronunciation'], row['name'], row['scientific_name']))

    with sqlite3.connect(DB) as conn:
        encyclopedia.bootstrap(conn)

    _database_ready = (str(DB.resolve()), DB.stat().st_ino, SAMPLE, CATALOG)


def ensure_database():
    with _database_lock:
        identity = (str(DB.resolve()), DB.stat().st_ino, SAMPLE, CATALOG) if DB.exists() else None
        if identity is None or identity != _database_ready:
            initialize_database()


@asynccontextmanager
async def lifespan(app):
    initialize_database()
    app.state.audio = create_service()
    app.state.parent_auth = ParentAuth(importer_root())
    try:
        yield
    finally:
        app.state.audio.close()


app = FastAPI(title='Bedtime Battle Stories', lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    if request.url.path.startswith('/api/admin/'):
        return await request_validation_error(request, exc)
    return await request_validation_exception_handler(request, exc)

app.include_router(audio_router)
app.include_router(library_router)
app.include_router(admin_router)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')


@app.get('/', response_class=HTMLResponse)
def home():
    return (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')


@app.get('/api/config')
def config():
    return {'sample_data': SAMPLE, 'catalog': CATALOG and not SAMPLE, 'idle_minutes': 5,
            'version': '3.0', 'catalog_review': 'Reference checks pending; measurements omitted'}


@app.get('/api/creatures')
def creatures(category: Literal['dinosaur', 'shark', 'marine_reptile'] | None = None,
              q: str = ''):
    ensure_database()
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM creatures ORDER BY name').fetchall()
        metadata = {r[0]: json.loads(r[1]) for r in conn.execute('SELECT creature_id, metadata FROM catalog_metadata')}
        result = []
        for row in rows:
            item = dict(row)
            extra = metadata.get(row['id'], {})
            for key in ['catalog_key','taxon_rank','source_url','review_status','pronunciation_note']:
                if key in extra:
                    item[key] = extra[key]
            result.append(item)
        enriched=encyclopedia.enrich(conn,result,os.environ.get('BBS_AUDIO_CACHE',ROOT/'data/audio_cache'))
        for item in enriched:item['eligible_for_tournament']=bool(HABITAT_ARENAS.get(item['habitat'],set()))
        selected=[r for r in enriched if (category is None or r['category']==category)
                  and (q.casefold() in r['name'].casefold() or q.casefold() in (r['scientific_name'] or '').casefold())]
        return sorted(selected,key=lambda r:r['name'].casefold())



def arenas_for(rows):
    arenas = {'land', 'water'}
    for row in rows:
        arenas &= HABITAT_ARENAS.get(row['habitat'], set())
    return arenas


@app.get('/api/selection/random')
def random_selection(category: Literal['dinosaur', 'shark', 'marine_reptile', 'ocean']):
    rows = [r for r in creatures() if r['category'] in {'shark', 'marine_reptile'}] if category == 'ocean' else creatures(category)
    arena='land' if category=='dinosaur' else 'water'
    rows=[row for row in rows if arena in arenas_for([row])]
    if len(rows) < 8:
        raise HTTPException(422, 'At least eight compatible creatures with known habitats are needed in this category')
    # Require a shared arena, then sample uniformly without replacement.
    # Mixed incompatible categories need a future explicit arena filter.
    if not arenas_for(rows):
        raise HTTPException(422, 'This category needs a compatible arena filter')
    return {'creature_ids': [r['id'] for r in random.sample(rows, 8)]}


class TournamentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    creature_ids: list[StrictInt] = Field(min_length=8, max_length=8)
    shuffle: bool = False
    realism: Literal['realistic', 'balanced', 'anything'] = 'balanced'
    duration: Literal['short', 'normal', 'long'] = 'normal'
    seed: StrictInt = Field(default_factory=lambda: random.SystemRandom().randrange(2**32), ge=0, lt=2**32)


@app.post('/api/tournament')
def tournament(request: TournamentRequest):
    if len(set(request.creature_ids)) != 8:
        raise HTTPException(422, 'Select exactly eight distinct creatures')
    by_id = {r['id']: r for r in creatures()}
    if any(i not in by_id for i in request.creature_ids):
        raise HTTPException(422, 'Unknown creature')
    selected = [by_id[i] for i in request.creature_ids]
    arenas = arenas_for(selected)
    if not arenas:
        raise HTTPException(422, 'These creatures do not share a suitable habitat')
    if request.shuffle:
        random.Random(request.seed).shuffle(selected)
    rounds = []
    for index, (name, count) in enumerate([('Quarterfinals', 4), ('Semifinals', 2), ('Championship', 1)]):
        matches = []
        for n in range(count):
            matches.append({'id': f'r{index}m{n}',
                            'left': selected[n * 2] if index == 0 else None,
                            'right': selected[n * 2 + 1] if index == 0 else None,
                            'winner': None, 'status': 'pending',
                            'sources': [] if index == 0 else [f'r{index-1}m{n*2}', f'r{index-1}m{n*2+1}']})
        rounds.append({'name': name, 'matches': matches})
    state = {'rounds': rounds, 'arena': sorted(arenas)[0], 'realism': request.realism,
             'duration': request.duration, 'entrant_ids': request.creature_ids, 'shuffle': request.shuffle}
    return progress(state, request.seed, 0, request.realism, request.duration)


class AdventureRequest(TournamentRequest):
    seed: StrictInt = Field(ge=0, lt=2**32)
    completed: StrictInt = Field(default=0, ge=0, le=7)


@app.post('/api/adventure')
def adventure(request: AdventureRequest):
    state = tournament(request)
    return progress(state, request.seed, request.completed, request.realism, request.duration)
