import os
import subprocess
import sys
from pathlib import Path


def test_built_frontend_and_api_are_served_by_one_local_server(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<title>OpenWorld</title>", encoding="utf-8")
    (frontend / "asset.js").write_text("window.example = true", encoding="utf-8")
    env = dict(
        os.environ,
        OPENWORLD_FRONTEND_DIR=str(frontend),
        OPENWORLD_DATA_DIR=str(tmp_path / "data"),
    )
    env.pop("OPENWORLD_DATABASE_URL", None)
    result = subprocess.run(
        [
            sys.executable, "-c",
            "from fastapi.testclient import TestClient; "
            "from app.main import app; from app.db import Base, engine; "
            "Base.metadata.create_all(engine); "
            "client = TestClient(app); "
            "assert client.get('/').text == '<title>OpenWorld</title>'; "
            "assert client.get('/asset.js').status_code == 200; "
            "assert client.get('/api/health').json()['status'] == 'ok'; "
            "assert client.get('/api/worlds').json() == []; "
            "assert client.get('/missing.js').status_code == 404",
        ],
        cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_missing_frontend_build_is_an_explicit_startup_error(tmp_path):
    env = dict(
        os.environ, OPENWORLD_FRONTEND_DIR=str(tmp_path / "missing"),
        OPENWORLD_DATA_DIR=str(tmp_path / "data"),
    )
    env.pop("OPENWORLD_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app"],
        cwd=Path(__file__).parents[1], env=env, capture_output=True,
    )
    assert result.returncode != 0
    assert b"Frontend-Build fehlt" in result.stderr
