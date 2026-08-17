"""Read-only ledger models and queries for the terminal run view."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


class LedgerReadError(Exception):
    """A user-facing failure while reading the ledger."""


@dataclass(frozen=True)
class Run:
    id: str
    app_version: str
    environment_snapshot_id: str
    agent_role: str
    declared_scope: str
    start_time: str
    end_time: str
    token_budget: int
    time_budget: int
    status: str


@dataclass(frozen=True)
class Event:
    sequence_number: int
    action_type: str
    request_response_summary: str
    artifact_reference: str
    policy_decision: str
    timestamp: str


@dataclass(frozen=True)
class Hypothesis:
    id: str
    submitted_by_run: str
    affected_app_rule: str
    concise_claim: str
    expected_evidence: str
    verification_status: str
    verifier_run_id: str | None


@dataclass(frozen=True)
class Finding:
    id: str
    hypothesis_id: str
    severity_rationale: str
    reproduction_steps: str
    remediation_direction: str
    evidence_references: str


@dataclass(frozen=True)
class RunView:
    run: Run
    events: tuple[Event, ...]
    hypotheses: tuple[Hypothesis, ...]
    findings: tuple[Finding, ...]


def _connect_read_only(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    if not path.is_file():
        raise LedgerReadError(f"ledger database does not exist: {path}")
    try:
        return sqlite3.connect(f"file:{quote(str(path.resolve()))}?mode=ro", uri=True)
    except (OSError, sqlite3.Error) as exc:
        raise LedgerReadError(f"ledger is unreadable: {path}") from exc


def _read_query(connection: sqlite3.Connection, query: str, parameters: tuple[object, ...] = ()) -> list[sqlite3.Row]:
    try:
        connection.row_factory = sqlite3.Row
        return connection.execute(query, parameters).fetchall()
    except sqlite3.Error as exc:
        raise LedgerReadError("ledger is unreadable") from exc


def _as_text(value: object) -> str:
    return "" if value is None else str(value)


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _latest_hypotheses(connection: sqlite3.Connection, run_id: str) -> list[Hypothesis]:
    rows = _read_query(
        connection,
        """SELECT rowid, id, submitted_by_run, affected_app_rule, concise_claim,
                  expected_evidence, verification_status, verifier_run_id
           FROM hypothesis ORDER BY rowid ASC""",
    )
    latest: dict[str, sqlite3.Row] = {}
    for row in rows:
        latest[_as_text(row["id"])] = row
    selected = [
        row for row in latest.values()
        if _as_text(row["submitted_by_run"]) == run_id
        or _as_text(row["verifier_run_id"]) == run_id
    ]
    selected.sort(key=lambda row: (_as_text(row["id"]), _as_int(row["rowid"])))
    return [
        Hypothesis(
            id=_as_text(row["id"]),
            submitted_by_run=_as_text(row["submitted_by_run"]),
            affected_app_rule=_as_text(row["affected_app_rule"]),
            concise_claim=_as_text(row["concise_claim"]),
            expected_evidence=_as_text(row["expected_evidence"]),
            verification_status=_as_text(row["verification_status"]),
            verifier_run_id=None if row["verifier_run_id"] is None else _as_text(row["verifier_run_id"]),
        )
        for row in selected
    ]


def read_run(run_id: str, database_path: str | Path = "data/ledger.db") -> RunView:
    """Read one run and its associated latest hypothesis revisions and findings."""
    connection = _connect_read_only(database_path)
    try:
        run_rows = _read_query(connection, "SELECT rowid, * FROM run WHERE id = ? ORDER BY rowid DESC LIMIT 1", (run_id,))
        if not run_rows:
            raise LedgerReadError(f"run ID not found: {run_id}")
        row = run_rows[0]
        run = Run(
            id=_as_text(row["id"]), app_version=_as_text(row["app_version"]),
            environment_snapshot_id=_as_text(row["environment_snapshot_id"]),
            agent_role=_as_text(row["agent_role"]), declared_scope=_as_text(row["declared_scope"]),
            start_time=_as_text(row["start_time"]), end_time=_as_text(row["end_time"]),
            token_budget=_as_int(row["token_budget"]), time_budget=_as_int(row["time_budget"]),
            status=_as_text(row["status"]),
        )
        events = tuple(
            Event(
                sequence_number=_as_int(event["sequence_number"]), action_type=_as_text(event["action_type"]),
                request_response_summary=_as_text(event["request_response_summary"]),
                artifact_reference=_as_text(event["artifact_reference"]),
                policy_decision=_as_text(event["policy_decision"]), timestamp=_as_text(event["timestamp"]),
            )
            for event in _read_query(
                connection,
                "SELECT rowid, * FROM event WHERE run_id = ? ORDER BY sequence_number ASC, rowid ASC",
                (run_id,),
            )
        )
        hypotheses = tuple(_latest_hypotheses(connection, run_id))
        hypothesis_ids = {hypothesis.id for hypothesis in hypotheses}
        findings = tuple(
            Finding(
                id=_as_text(finding["id"]), hypothesis_id=_as_text(finding["hypothesis_id"]),
                severity_rationale=_as_text(finding["severity_rationale"]),
                reproduction_steps=_as_text(finding["reproduction_steps"]),
                remediation_direction=_as_text(finding["remediation_direction"]),
                evidence_references=_as_text(finding["evidence_references"]),
            )
            for finding in _read_query(connection, "SELECT rowid, * FROM finding ORDER BY rowid ASC")
            if _as_text(finding["hypothesis_id"]) in hypothesis_ids
        )
        return RunView(run, events, hypotheses, findings)
    finally:
        connection.close()


def read_latest_run(database_path: str | Path = "data/ledger.db") -> RunView:
    """Read the most recently inserted run without changing the database."""
    connection = _connect_read_only(database_path)
    try:
        rows = _read_query(connection, "SELECT id FROM run ORDER BY rowid DESC LIMIT 1")
        if not rows:
            raise LedgerReadError("no runs exist in the ledger")
        run_id = _as_text(rows[0]["id"])
    finally:
        connection.close()
    return read_run(run_id, database_path)


def read_latest_verifier_run(database_path: str | Path = "data/ledger.db") -> RunView:
    """Read the most recently inserted verifier run without changing the database."""
    connection = _connect_read_only(database_path)
    try:
        rows = _read_query(
            connection,
            "SELECT id FROM run WHERE agent_role = ? AND status = ? ORDER BY rowid DESC LIMIT 1",
            ("verifier", "completed"),
        )
        if not rows:
            raise LedgerReadError("no completed verifier runs exist in the ledger")
        run_id = _as_text(rows[0]["id"])
    finally:
        connection.close()
    return read_run(run_id, database_path)
