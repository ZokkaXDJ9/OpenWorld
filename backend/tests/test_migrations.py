import os
import sqlite3
import subprocess
from pathlib import Path

from sqlalchemy import inspect

from app.db import Base, make_engine


def test_migration_matches_models_and_can_downgrade(tmp_path):
    backend = Path(__file__).parents[1]
    executable = Path(__import__("sys").executable)
    env = dict(os.environ, OPENWORLD_DATA_DIR=str(tmp_path))
    env.pop("OPENWORLD_DATABASE_URL", None)
    subprocess.run(
        [str(executable), "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    engine = make_engine(f"sqlite:///{tmp_path / 'openworld.db'}")
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in inspector.get_columns(name)} == set(table.columns.keys())
        assert {index["name"] for index in inspector.get_indexes(name)} == {
            index.name for index in table.indexes
        }
    engine.dispose()
    subprocess.run(
        [str(executable), "-m", "alembic", "downgrade", "base"],
        cwd=backend,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    engine = make_engine(f"sqlite:///{tmp_path / 'openworld.db'}")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_location_order_migration_preserves_existing_world_data(tmp_path):
    backend = Path(__file__).parents[1]
    executable = Path(__import__("sys").executable)
    env = dict(os.environ, OPENWORLD_DATA_DIR=str(tmp_path))
    env.pop("OPENWORLD_DATABASE_URL", None)
    for target in ("0001", "head"):
        subprocess.run(
            [str(executable), "-m", "alembic", "upgrade", target],
            cwd=backend,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        if target == "0001":
            with sqlite3.connect(tmp_path / "openworld.db") as db:
                db.execute(
                    "INSERT INTO worlds VALUES (?, ?, ?, ?, ?, ?)",
                    ("world", "Drachenwelt", "Unverändert", "[]", "{}", 4),
                )
                for item_id, parent in [("a", None), ("b", None), ("child", "a")]:
                    db.execute(
                        "INSERT INTO locations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (item_id, "world", parent, item_id, "Ort", "Lore", "[]", "[]", "{}", 7),
                    )
                before = db.execute("SELECT * FROM locations").fetchall()
    with sqlite3.connect(tmp_path / "openworld.db") as db:
        after = db.execute("SELECT * FROM locations").fetchall()
        assert [row[:-1] for row in after] == before
        assert [row[-1] for row in after] == [0, 1, 0]
        assert db.execute("SELECT revision FROM worlds").fetchone() == (4,)
    subprocess.run(
        [str(executable), "-m", "alembic", "downgrade", "0001"],
        cwd=backend,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(tmp_path / "openworld.db") as db:
        assert db.execute("SELECT * FROM locations").fetchall() == before


def test_phase2_migration_preserves_populated_messages_knowledge_and_profiles(tmp_path):
    backend = Path(__file__).parents[1]
    env = dict(os.environ, OPENWORLD_DATA_DIR=str(tmp_path))
    env.pop("OPENWORLD_DATABASE_URL", None)

    def migrate(target):
        subprocess.run(
            [__import__("sys").executable, "-m", "alembic", "upgrade", target],
            cwd=backend,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    migrate("0002")
    with sqlite3.connect(tmp_path / "openworld.db") as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO worlds VALUES ('w','Welt','Lore','[]','{}',4)")
        db.execute(
            "INSERT INTO characters VALUES ('c','w','Lumia','Profil',"
            """'{"Persoenlichkeit":"Ruhig"}','{}','[]',NULL,NULL,'unknown',7)"""
        )
        db.execute("INSERT INTO conversations VALUES ('chat','w','c','Alt','2020-01-01 12:00:00')")
        db.execute(
            "INSERT INTO messages VALUES ('msg','chat','user','Wie geht es dir?',"
            "'complete','2020-01-01 12:00:00',1)"
        )
        db.execute(
            "INSERT INTO messages VALUES ('answer','chat','assistant','Gut.',"
            "'complete','2020-01-01 12:00:01',2)"
        )
        db.execute(
            "INSERT INTO knowledge VALUES ('k','w','c','received','Wie geht es dir?',"
            "'Benutzeraussage',50,0,'msg','2020-01-01 12:00:00',3)"
        )
        columns = {
            table: [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
            for table in ("worlds", "characters", "conversations", "messages", "knowledge")
        }
        before = {
            table: db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() for table in columns
        }
    migrate("head")
    with sqlite3.connect(tmp_path / "openworld.db") as db:
        for table, names in columns.items():
            assert (
                db.execute(f"SELECT {','.join(names)} FROM {table} ORDER BY id").fetchall()
                == before[table]
            )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT kind, confidence, origin FROM knowledge").fetchone() == (
            "received",
            50,
            "legacy",
        )
        assert db.execute(
            "SELECT speaker_character_id FROM messages WHERE id='answer'"
        ).fetchone() == ("c",)
        assert db.execute("SELECT count(*) FROM events").fetchone() == (0,)
