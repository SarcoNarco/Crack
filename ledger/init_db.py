"""Initialize the Crack SQLite ledger from the migration-style schema."""

import sqlite3
from pathlib import Path
from typing import Final


SCHEMA_PATH: Final = Path(__file__).with_name("migrations") / "0001_initial.sql"


def initialize_database(database_path: str | Path = "data/ledger.db") -> Path:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return path


def record_event(
    *,
    run_id: str,
    sequence_number: int,
    action_type: str,
    request_response_summary: str,
    artifact_reference: str,
    policy_decision: str,
    timestamp: str,
    database_path: str | Path = "data/ledger.db",
) -> None:
    """Insert one evidence event through the ledger-owned persistence boundary."""
    path = initialize_database(database_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO event (
                run_id,
                sequence_number,
                action_type,
                request_response_summary,
                artifact_reference,
                policy_decision,
                timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                sequence_number,
                action_type,
                request_response_summary,
                artifact_reference,
                policy_decision,
                timestamp,
            ),
        )


if __name__ == "__main__":
    print(initialize_database())
