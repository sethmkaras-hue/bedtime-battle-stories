import os
import tempfile
from fastapi.testclient import TestClient
from app import main

def test_home():
    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200

def test_empty_creature_library():
    with tempfile.TemporaryDirectory() as tmp:
        original = main.DB
        main.DB = __import__("pathlib").Path(tmp) / "creatures.sqlite3"
        try:
            with TestClient(main.app) as client:
                assert client.get("/api/creatures").json() == []
        finally:
            main.DB = original

def test_invalid_tournament():
    with TestClient(main.app) as client:
        assert client.post("/api/tournament", json={"creature_ids": [1, 2]}).status_code == 422
