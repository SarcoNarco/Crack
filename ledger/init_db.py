"""Initialize the Crack SQLite ledger from the migration-style schema."""

import sqlite3
from pathlib import Path


SCHEMA_PATH = Path(__file__).with_name("migrations") / "0001_initial.sql"


def initialize_database(database_path: str | Path = "data/ledger.db") -> Path:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return path


if __name__ == "__main__":
    print(initialize_database())
