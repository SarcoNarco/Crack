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


def record_run(
    *,
    run_id: str,
    app_version: str,
    environment_snapshot_id: str,
    agent_role: str,
    declared_scope: str,
    start_time: str,
    end_time: str,
    token_budget: int,
    time_budget: int,
    status: str,
    database_path: str | Path = "data/ledger.db",
) -> None:
    """Insert one run record through the ledger-owned persistence boundary."""
    path = initialize_database(database_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO run (
                id, app_version, environment_snapshot_id, agent_role, declared_scope,
                start_time, end_time, token_budget, time_budget, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                app_version,
                environment_snapshot_id,
                agent_role,
                declared_scope,
                start_time,
                end_time,
                token_budget,
                time_budget,
                status,
            ),
        )


if __name__ == "__main__":
    print(initialize_database())
