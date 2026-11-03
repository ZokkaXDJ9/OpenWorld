"""Start a real backend with a disposable, migrated database for browser tests."""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

if __name__ == "__main__":
    with TemporaryDirectory(prefix="openworld-e2e-") as directory:
        os.environ["OPENWORLD_DATA_DIR"] = directory
        os.environ.pop("OPENWORLD_DATABASE_URL", None)
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).parents[1],
            check=True,
        )
        uvicorn.run("app.main:app", host="127.0.0.1", port=18000)
