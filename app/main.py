from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import json
import os
import random
import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get('BBS_DB_PATH', ROOT / 'data' / ('sample.sqlite3' if os.environ.get('BBS_SAMPLE_DATA') == '1' else 'creatures.sqlite3')))
SAMPLE = os.environ.get('BBS_SAMPLE_DATA') == '1'
# A matchup needs a shared arena across every participant. Extend here as
# verified species gain more specific habitat requirements.
HABITAT_ARENAS = {'land': {'land'}, 'marine': {'water'},
                  'semi_aquatic': {'land', 'water'}}


def initialize_database():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS creatures (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            scientific_name TEXT, category TEXT NOT NULL, habitat TEXT NOT NULL,
            length_m REAL, weight_kg REAL, diet TEXT, offense TEXT, defense TEXT,
            locomotion TEXT, description TEXT, image_reference TEXT, pronunciation TEXT
        )''')
        if SAMPLE:
            rows = json.loads((ROOT / 'data' / 'sample_creatures.json').read_text())
            for row in rows:
                keys = list(row)
                conn.execute(f"INSERT OR IGNORE INTO creatures ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", list(row.values()))


@asynccontextmanager
async def lifespan(app):
    initialize_database()
    yield


app = FastAPI(title='Bedtime Battle Stories', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')


@app.get('/', response_class=HTMLResponse)
def home():
    return (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')


@app.get('/api/config')
def config():
    return {'sample_data': SAMPLE, 'idle_minutes': 5}


@app.get('/api/creatures')
def creatures(category: Literal['dinosaur', 'shark', 'marine_reptile'] | None = None,
              q: str = ''):
    initialize_database()
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM creatures ORDER BY name').fetchall()
        return [dict(r) for r in rows if (category is None or r['category'] == category)
                and (q.casefold() in r['name'].casefold() or q.casefold() in (r['scientific_name'] or '').casefold())]


def arenas_for(rows):
    arenas = {'land', 'water'}
    for row in rows:
        arenas &= HABITAT_ARENAS.get(row['habitat'], set())
    return arenas


@app.get('/api/selection/random')
def random_selection(category: Literal['dinosaur', 'shark', 'marine_reptile']):
    rows = creatures(category)
    if len(rows) < 8:
        raise HTTPException(422, 'At least eight creatures are needed in this category')
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
        random.shuffle(selected)
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
    return {'rounds': rounds, 'arena': sorted(arenas)[0], 'realism': request.realism,
            'duration': request.duration, 'placeholder': True}
