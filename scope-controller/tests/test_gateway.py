from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

import scope_controller
from ledger import init_db
from scope_controller import _gateway


DEMO_TOKEN_A = "token-account-a-fixed"


def test_public_api_contains_only_the_declared_capabilities() -> None:
    assert scope_controller.__all__ == [
        "read_source",
        "query_app_map",
        "call_app_endpoint",
        "reset_environment",
        "record_evidence",
        "submit_hypothesis",
        "update_verification_status",
        "record_finding",
    ]
    assert all(callable(getattr(scope_controller, name)) for name in scope_controller.__all__)
    assert not hasattr(scope_controller, "run_shell")
    assert not hasattr(scope_controller, "http_client")
    assert not hasattr(scope_controller, "open")


def test_read_source_reads_only_from_app_under_test() -> None:
    source = scope_controller.read_source("app/main.py")
    assert "app = FastAPI" in source


def test_read_source_rejects_parent_path_traversal() -> None:
    with pytest.raises(PermissionError, match="inside app-under-test"):
        scope_controller.read_source("../AGENTS.md")


def test_read_source_rejects_absolute_outside_path() -> None:
    with pytest.raises(PermissionError, match="inside app-under-test"):
        scope_controller.read_source("/etc/passwd")


def test_read_source_rejects_app_answer_key_readme() -> None:
    with pytest.raises(PermissionError, match="README.md is off-limits"):
        scope_controller.read_source("README.md")


def test_read_source_rejects_symlink_that_escapes_app_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app_root = tmp_path / "app-under-test"
    app_root.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("outside", encoding="utf-8")
    link = app_root / "escape-test-link"
    link.symlink_to(outside_file)
    monkeypatch.setattr(_gateway, "_APP_ROOT", app_root)

    with pytest.raises(PermissionError, match="inside app-under-test"):
        scope_controller.read_source(link)


def test_query_app_map_is_an_explicit_sprint_4_stub() -> None:
    with pytest.raises(NotImplementedError, match="Sprint 4"):
        scope_controller.query_app_map()


@pytest.mark.parametrize("method", ["PATCH", "OPTIONS", "TRACE", "CONNECT", "SHELL"])
def test_call_app_endpoint_rejects_non_allowlisted_methods(method: str) -> None:
    with pytest.raises(PermissionError, match="GET, POST, PUT, DELETE"):
        scope_controller.call_app_endpoint(method, "/health", DEMO_TOKEN_A)


def test_call_app_endpoint_rejects_non_allowlisted_token() -> None:
    with pytest.raises(PermissionError, match="not a seeded demo token"):
        scope_controller.call_app_endpoint("GET", "/health", "real-or-stolen-token")


@pytest.mark.parametrize(
    "path",
    [
        "https://example.com/records/1",
        "http://127.0.0.1:9999/records/1",
        "//example.com/records/1",
        "example.com/records/1",
    ],
)
def test_call_app_endpoint_rejects_every_alternate_host_or_url(path: str) -> None:
    with pytest.raises(PermissionError, match="fixed origin http://127.0.0.1:8100"):
        scope_controller.call_app_endpoint("GET", path, DEMO_TOKEN_A)


@pytest.mark.parametrize("path", ["/health\r\nHost: example.com", "/health\\@example.com"])
def test_call_app_endpoint_rejects_request_smuggling_paths(path: str) -> None:
    with pytest.raises(PermissionError, match="malformed endpoint path"):
        scope_controller.call_app_endpoint("GET", path, DEMO_TOKEN_A)


def test_no_exposed_function_can_invoke_a_shell_command() -> None:
    with pytest.raises(AttributeError, match="run_shell"):
        getattr(scope_controller, "run_shell")("id")
    with pytest.raises(PermissionError, match="method must be one of"):
        scope_controller.call_app_endpoint("SHELL", "/bin/sh -c id", DEMO_TOKEN_A)

    gateway_source = inspect.getsource(_gateway)
    banned_runtime_calls = ("subprocess", "os.system", "os.popen", "shell=True")
    assert all(banned not in gateway_source for banned in banned_runtime_calls)


def test_reset_environment_calls_fixed_seed_and_ignores_environment_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outside_database = tmp_path / "must-not-be-created.db"
    monkeypatch.setenv("APP_DB_PATH", str(outside_database))

    scope_controller.reset_environment()

    assert not outside_database.exists()
    with sqlite3.connect(_gateway._APP_DATABASE_PATH) as connection:
        accounts = connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        records = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    assert (accounts, records) == (2, 2)


def test_reset_environment_accepts_no_command_argument() -> None:
    with pytest.raises(TypeError, match="positional argument"):
        scope_controller.reset_environment("id")


def test_record_evidence_writes_only_an_event_via_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger_path = tmp_path / "ledger.db"
    monkeypatch.setattr(_gateway, "_LEDGER_DATABASE_PATH", ledger_path)

    scope_controller.record_evidence(
        run_id="run-sprint-2-test",
        sequence_number=1,
        action_type="rejection",
        request_response_summary="Blocked alternate host",
        artifact_reference="test://alternate-host",
        policy_decision="blocked",
    )

    with sqlite3.connect(ledger_path) as connection:
        event = connection.execute(
            """
            SELECT run_id, sequence_number, action_type, request_response_summary,
                   artifact_reference, policy_decision, timestamp
            FROM event
            """
        ).fetchone()
        untouched_counts = [
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("run", "hypothesis", "finding")
        ]

    assert event[:6] == (
        "run-sprint-2-test",
        1,
        "rejection",
        "Blocked alternate host",
        "test://alternate-host",
        "blocked",
    )
    assert event[6]
    assert untouched_counts == [0, 0, 0]


def test_record_evidence_rejects_attempted_database_or_sql_parameters() -> None:
    signature = inspect.signature(scope_controller.record_evidence)
    assert "database_path" not in signature.parameters
    assert "sql" not in signature.parameters

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        scope_controller.record_evidence(
            run_id="run-1",
            sequence_number=1,
            action_type="attempt",
            request_response_summary="attempted raw SQL",
            artifact_reference="none",
            policy_decision="blocked",
            sql="DROP TABLE event",
        )


def test_submit_hypothesis_writes_unverified_row_and_audit_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger_path = tmp_path / "ledger.db"
    monkeypatch.setattr(_gateway, "_LEDGER_DATABASE_PATH", ledger_path)

    hypothesis_id = scope_controller.submit_hypothesis(
        "run-identity-1",
        "GET /records/{id} checks record ownership",
        "Account B can read Account A's record",
        "A seeded Account B request returns Account A's record",
    )

    with sqlite3.connect(ledger_path) as connection:
        hypothesis = connection.execute(
            """
            SELECT id, submitted_by_run, affected_app_rule, concise_claim,
                   expected_evidence, verification_status, verifier_run_id
            FROM hypothesis
            """
        ).fetchone()
        event = connection.execute(
            "SELECT run_id, action_type, policy_decision FROM event"
        ).fetchone()

    assert hypothesis == (
        hypothesis_id,
        "run-identity-1",
        "GET /records/{id} checks record ownership",
        "Account B can read Account A's record",
        "A seeded Account B request returns Account A's record",
        "unverified",
        None,
    )
    assert event == ("run-identity-1", "hypothesis_submitted", "allowed")


def test_record_finding_rejects_unverified_hypothesis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger_path = tmp_path / "ledger.db"
    monkeypatch.setattr(_gateway, "_LEDGER_DATABASE_PATH", ledger_path)
    hypothesis_id = scope_controller.submit_hypothesis(
        "run-identity-2", "rule", "claim", "evidence"
    )

    with pytest.raises(ValueError, match="only verified hypotheses can become findings"):
        scope_controller.record_finding(
            hypothesis_id,
            "high impact",
            "1. Send request",
            "event://request-1",
            "Enforce record ownership",
        )

    with sqlite3.connect(ledger_path) as connection:
        finding_count = connection.execute("SELECT COUNT(*) FROM finding").fetchone()[0]
    assert finding_count == 0


def test_verification_status_is_append_only_and_audited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger_path = tmp_path / "ledger.db"
    monkeypatch.setattr(_gateway, "_LEDGER_DATABASE_PATH", ledger_path)
    hypothesis_id = scope_controller.submit_hypothesis(
        "run-identity-3", "rule", "claim", "evidence"
    )

    scope_controller.update_verification_status(
        hypothesis_id, "verified", "run-verifier-3"
    )

    with sqlite3.connect(ledger_path) as connection:
        revisions = connection.execute(
            """
            SELECT id, concise_claim, verification_status, verifier_run_id
            FROM hypothesis
            WHERE id = ?
            ORDER BY rowid
            """,
            (hypothesis_id,),
        ).fetchall()
        status_events = connection.execute(
            """
            SELECT run_id, action_type, policy_decision
            FROM event
            WHERE action_type = 'hypothesis_status_updated'
            """
        ).fetchall()

    assert revisions == [
        (hypothesis_id, "claim", "unverified", None),
        (hypothesis_id, "claim", "verified", "run-verifier-3"),
    ]
    assert status_events == [("run-verifier-3", "hypothesis_status_updated", "allowed")]


def test_record_finding_succeeds_after_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger_path = tmp_path / "ledger.db"
    monkeypatch.setattr(_gateway, "_LEDGER_DATABASE_PATH", ledger_path)
    hypothesis_id = scope_controller.submit_hypothesis(
        "run-identity-4", "rule", "claim", "evidence"
    )
    scope_controller.update_verification_status(
        hypothesis_id, "verified", "run-verifier-4"
    )

    finding_id = scope_controller.record_finding(
        hypothesis_id,
        "High impact: cross-account record disclosure",
        "1. Authenticate as Account B. 2. Request Account A's record ID.",
        "event://run-verifier-4/2",
        "Compare the authenticated account to the record owner before returning it.",
    )

    with sqlite3.connect(ledger_path) as connection:
        finding = connection.execute(
            """
            SELECT id, hypothesis_id, severity_rationale, reproduction_steps,
                   evidence_references, remediation_direction
            FROM finding
            """
        ).fetchone()

    assert finding == (
        finding_id,
        hypothesis_id,
        "High impact: cross-account record disclosure",
        "1. Authenticate as Account B. 2. Request Account A's record ID.",
        "event://run-verifier-4/2",
        "Compare the authenticated account to the record owner before returning it.",
    )


def test_no_generic_hypothesis_update_or_delete_path_exists() -> None:
    assert not hasattr(scope_controller, "update_hypothesis")
    assert not hasattr(scope_controller, "delete_hypothesis")
    ledger_source = inspect.getsource(init_db)
    assert "UPDATE hypothesis" not in ledger_source
    assert "DELETE FROM hypothesis" not in ledger_source


def test_verification_status_rejects_unknown_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger_path = tmp_path / "ledger.db"
    monkeypatch.setattr(_gateway, "_LEDGER_DATABASE_PATH", ledger_path)
    hypothesis_id = scope_controller.submit_hypothesis(
        "run-identity-5", "rule", "claim", "evidence"
    )

    with pytest.raises(ValueError, match="status must be one of"):
        scope_controller.update_verification_status(
            hypothesis_id, "confirmed", "run-verifier-5"
        )
