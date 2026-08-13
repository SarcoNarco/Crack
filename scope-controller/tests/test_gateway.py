from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

import scope_controller
from scope_controller import _gateway


DEMO_TOKEN_A = "token-account-a-fixed"


def test_public_api_contains_only_the_five_capabilities() -> None:
    assert scope_controller.__all__ == [
        "read_source",
        "query_app_map",
        "call_app_endpoint",
        "reset_environment",
        "record_evidence",
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
