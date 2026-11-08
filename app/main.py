from pathlib import Path
import random
import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "creatures.sqlite3"
app = FastAPI(title="Bedtime Battle Stories")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

def initialize_database():
    DB.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS creatures (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            scientific_name TEXT,
            category TEXT NOT NULL,
            habitat TEXT NOT NULL,
            length_m REAL,
            weight_kg REAL,
            diet TEXT,
            offense TEXT,
            defense TEXT,
            locomotion TEXT,
            description TEXT,
            image_reference TEXT,
            pronunciation TEXT
        )""")

@app.on_event("startup")
def startup():
    initialize_database()

@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/api/creatures")
def creatures(category: str | None = None):
    initialize_database()
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        if category:
            rows = conn.execute("SELECT * FROM creatures WHERE category = ? ORDER BY name", (category,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM creatures ORDER BY name").fetchall()
        return [dict(row) for row in rows]

class TournamentRequest(BaseModel):
    creature_ids: list[int]
    shuffle: bool = False
    realism: str = "balanced"
    duration: str = "normal"

@app.post("/api/tournament")
def tournament(request: TournamentRequest):
    if len(request.creature_ids) != 8 or len(set(request.creature_ids)) != 8:
        raise HTTPException(422, "Select exactly eight distinct creatures")
    if request.realism not in {"realistic", "balanced", "anything"}:
        raise HTTPException(422, "Invalid realism")
    if request.duration not in {"short", "normal", "long"}:
        raise HTTPException(422, "Invalid duration")
    initialize_database()
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        selected = []
        for creature_id in request.creature_ids:
            row = conn.execute("SELECT * FROM creatures WHERE id = ?", (creature_id,)).fetchone()
            if row is None:
                raise HTTPException(422, f"Unknown creature: {creature_id}")
            selected.append(dict(row))
    if request.shuffle:
        random.shuffle(selected)
    habitats = {c["habitat"] for c in selected}
    if "land" in habitats and "marine" in habitats:
        raise HTTPException(422, "Land and marine creatures cannot compete together")
    return {"rounds": [
        {"name": "Quarterfinals", "matches": [{"left": selected[i], "right": selected[i+1], "winner": None} for i in range(0,8,2)]},
        {"name": "Semifinals", "matches": [{"left": None, "right": None, "winner": None} for _ in range(2)]},
        {"name": "Championship", "matches": [{"left": None, "right": None, "winner": None}]}
    ], "realism": request.realism, "duration": request.duration, "placeholder": True}
