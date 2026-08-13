"""Initialize the Crack SQLite ledger from the migration-style schema."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4


SCHEMA_PATH: Final = Path(__file__).with_name("migrations") / "0001_initial.sql"


def initialize_database(database_path: str | Path = "data/ledger.db") -> Path:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return path


def _next_event_sequence(connection: sqlite3.Connection, run_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM event WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])


def _insert_event(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    action_type: str,
    request_response_summary: str,
    artifact_reference: str,
    policy_decision: str,
) -> None:
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
            _next_event_sequence(connection, run_id),
            action_type,
            request_response_summary,
            artifact_reference,
            policy_decision,
            datetime.now(UTC).isoformat(),
        ),
    )


def _latest_hypothesis(
    connection: sqlite3.Connection, hypothesis_id: str
) -> tuple[str, str, str, str, str, str, str | None] | None:
    """Read the latest append-only revision for a hypothesis ID."""
    return connection.execute(
        """
        SELECT id, submitted_by_run, affected_app_rule, concise_claim,
               expected_evidence, verification_status, verifier_run_id
        FROM hypothesis
        WHERE id = ?
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (hypothesis_id,),
    ).fetchone()


def _insert_hypothesis(
    *,
    hypothesis_id: str,
    run_id: str,
    affected_app_rule: str,
    concise_claim: str,
    expected_evidence: str,
    database_path: str | Path,
) -> None:
    """Persist one hypothesis revision and its submission audit event."""
    path = initialize_database(database_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO hypothesis (
                id, submitted_by_run, affected_app_rule, concise_claim,
                expected_evidence, verification_status, verifier_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hypothesis_id,
                run_id,
                affected_app_rule,
                concise_claim,
                expected_evidence,
                "unverified",
                None,
            ),
        )
        _insert_event(
            connection,
            run_id=run_id,
            action_type="hypothesis_submitted",
            request_response_summary=f"Submitted hypothesis {hypothesis_id}",
            artifact_reference=f"ledger://hypothesis/{hypothesis_id}",
            policy_decision="allowed",
        )


def _append_verification_status(
    *,
    hypothesis_id: str,
    status: str,
    verifier_run_id: str,
    database_path: str | Path,
) -> None:
    """Append a status revision without mutating any existing hypothesis row."""
    path = initialize_database(database_path)
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = _latest_hypothesis(connection, hypothesis_id)
        if current is None:
            raise ValueError(f"hypothesis {hypothesis_id!r} was not found")

        connection.execute(
            """
            INSERT INTO hypothesis (
                id, submitted_by_run, affected_app_rule, concise_claim,
                expected_evidence, verification_status, verifier_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (*current[:5], status, verifier_run_id),
        )
        _insert_event(
            connection,
            run_id=verifier_run_id,
            action_type="hypothesis_status_updated",
            request_response_summary=(
                f"Hypothesis {hypothesis_id} verification status is now {status}"
            ),
            artifact_reference=f"ledger://hypothesis/{hypothesis_id}",
            policy_decision="allowed",
        )


def _insert_finding(
    *,
    hypothesis_id: str,
    severity_rationale: str,
    reproduction_steps: str,
    evidence_references: str,
    remediation_direction: str,
    database_path: str | Path,
) -> str:
    """Persist a finding only for the latest verified hypothesis revision."""
    path = initialize_database(database_path)
    finding_id = str(uuid4())
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = _latest_hypothesis(connection, hypothesis_id)
        if current is None:
            raise ValueError(f"hypothesis {hypothesis_id!r} was not found")
        if current[5] != "verified":
            raise ValueError(
                f"hypothesis {hypothesis_id!r} is {current[5]!r}; only verified hypotheses can become findings"
            )

        connection.execute(
            """
            INSERT INTO finding (
                id, hypothesis_id, severity_rationale, reproduction_steps,
                evidence_references, remediation_direction
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                finding_id,
                hypothesis_id,
                severity_rationale,
                reproduction_steps,
                evidence_references,
                remediation_direction,
            ),
        )
        _insert_event(
            connection,
            run_id=current[6] or current[1],
            action_type="finding_recorded",
            request_response_summary=f"Recorded finding {finding_id}",
            artifact_reference=f"ledger://finding/{finding_id}",
            policy_decision="allowed",
        )
    return finding_id


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
