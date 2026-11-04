import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from test_events import extract, extracted_event, queue_source


def test_0005_preserves_every_original_column_and_row_of_populated_0004_database(eldoria):
    e = eldoria
    _, job_id = queue_source(e)
    assert extract(e, job_id, {"events": [extracted_event(e)]})["status"] == "complete"
    engine = e["factory"].kw["bind"]
    source = engine.url.database
    database = str(Path(source).with_name("migration-preservation.db"))
    engine.dispose()
    env = dict(
        os.environ,
        OPENWORLD_DATABASE_URL=str(engine.url.set(database=database)),
        OPENWORLD_DATA_DIR=str(Path(database).parent),
    )

    def migrate(*arguments):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=Path(__file__).parents[1],
            env=env,
            check=False,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")

    migrate("upgrade", "0004")
    with sqlite3.connect(database) as db:
        names = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
            )
        ]
        columns = {
            name: [row[1] for row in db.execute(f'PRAGMA table_info("{name}")')] for name in names
        }
        with sqlite3.connect(source) as original:
            for name, fields in columns.items():
                selected = ",".join(f'"{field}"' for field in fields)
                rows = original.execute(f'SELECT {selected} FROM "{name}"').fetchall()
                placeholders = ",".join("?" for _ in fields)
                db.executemany(f'INSERT INTO "{name}" ({selected}) VALUES ({placeholders})', rows)
        before = {
            name: sorted(db.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr)
            for name in names
        }
        assert before["messages"] and before["extraction_job_sources"]
        assert before["event_sources"] and before["event_mutations"]
    migrate("upgrade", "head")
    with sqlite3.connect(database) as db:
        for name, fields in columns.items():
            selected = ",".join(f'"{field}"' for field in fields)
            assert (
                sorted(db.execute(f'SELECT {selected} FROM "{name}"').fetchall(), key=repr)
                == before[name]
            )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT kind FROM conversations").fetchall() == [("single",)]
        assert db.execute("SELECT character_id FROM conversation_participants").fetchall() == [
            (e["lumia"]["id"],)
        ]
