from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from coordinator.demo import DemoResult
from coordinator.live_events import (
    ActiveRunError,
    EventJournal,
    LiveRunManager,
    PresentationEvent,
    ReplayError,
)
from coordinator.main import create_app


def _completed_runner(**kwargs: object) -> DemoResult:
    progress = kwargs["progress"]
    session_id = str(kwargs["session_id"])
    output_root = Path(kwargs["output_root"])
    assert callable(progress)
    progress(
        event_type="preflight.started", stage="preflight", state="active",
        logical_role="coordinator", headline="Fixed preflight started",
        explanation="Only fixed local dependencies are checked.", metadata={}, reference=None,
    )
    progress(
        event_type="preflight.completed", stage="preflight", state="completed",
        logical_role="coordinator", headline="Fixed preflight completed",
        explanation="The local dependencies are ready.",
        metadata={"role_bindings": ["mapper · fake · fixture"]}, reference=None,
    )
    progress(
        event_type="consensus.completed", stage="consensus", state="completed",
        logical_role="ordinary_code", headline="Code-owned verdict: unverified",
        explanation="Both deterministic checks did not reproduce the boundary condition.",
        metadata={"check_1_satisfied": False, "check_2_satisfied": False, "verdict": "unverified"},
        reference="ledger://run/verifier-fixture/event/0",
    )
    progress(
        event_type="session.completed", stage="session", state="completed",
        logical_role="coordinator", headline="Contained verification run completed",
        explanation="The fixed synthetic workflow completed without a finding.",
        metadata={
            "verdict": "unverified", "verifier_run_id": "verifier-fixture",
            "finding_id": None, "report_url": f"/api/demo-runs/{session_id}/report",
        },
        reference="ledger://run/verifier-fixture",
    )
    manifest = output_root / session_id / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    return DemoResult(session_id, manifest, 1, "verifier-fixture", "unverified", None)


def _failed_runner(**kwargs: object) -> DemoResult:
    progress = kwargs["progress"]
    session_id = str(kwargs["session_id"])
    output_root = Path(kwargs["output_root"])
    assert callable(progress)
    progress(
        event_type="mapper.activated", stage="mapper", state="active",
        logical_role="mapper", headline="Source-only mapper activated",
        explanation="The fixed source allowlist is being mapped.", metadata={}, reference=None,
    )
    progress(
        event_type="session.failed", stage="mapper", state="failed",
        logical_role="coordinator", headline="Contained run stopped safely",
        explanation="The mapper failed and downstream stages were not activated.",
        metadata={"failed_stage": "mapper", "error_code": "stage_execution_failed"},
        reference=None,
    )
    manifest = output_root / session_id / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    return DemoResult(session_id, manifest, 2, None, None, None, "mapper")


def _manager(tmp_path: Path, runner=_completed_runner) -> LiveRunManager:
    return LiveRunManager(
        output_root=tmp_path / "demo",
        database_path=tmp_path / "ledger.db",
        dependencies_factory=lambda: SimpleNamespace(),  # type: ignore[arg-type]
        runner=runner,
    )


def _wait_for_terminal(manager: LiveRunManager, session_id: str) -> tuple[PresentationEvent, ...]:
    for _ in range(100):
        events = manager.journal(session_id).replay()
        if events[-1].type in {"session.completed", "session.failed"}:
            return events
        time.sleep(0.01)
    raise AssertionError("fixture run did not reach a terminal presentation event")


def test_start_accepts_only_empty_or_fixed_request_and_generates_session_id(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    client = TestClient(create_app(manager))
    rejected = client.post("/api/demo-runs", json={"target": "https://example.invalid"})
    assert rejected.status_code == 422

    accepted = client.post("/api/demo-runs", json={"confirmation": "start-contained-demo"})
    assert accepted.status_code == 202
    session_id = accepted.json()["session_id"]
    assert session_id.startswith("demo:")
    assert "target" not in accepted.text and "provider" not in accepted.text
    _wait_for_terminal(manager, session_id)


def test_empty_body_is_accepted_and_status_is_fixed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    client = TestClient(create_app(manager))
    response = client.post("/api/demo-runs")
    assert response.status_code == 202
    session_id = response.json()["session_id"]
    _wait_for_terminal(manager, session_id)
    status = client.get(f"/api/demo-runs/{session_id}")
    assert status.status_code == 200
    assert set(status.json()) == {
        "session_id", "state", "stage", "last_sequence", "terminal", "events_url",
    }


def test_only_one_active_run_is_allowed(tmp_path: Path) -> None:
    release = threading.Event()

    def blocked_runner(**kwargs: object) -> DemoResult:
        release.wait(timeout=2)
        return _completed_runner(**kwargs)

    manager = _manager(tmp_path, blocked_runner)
    first = manager.start()
    with pytest.raises(ActiveRunError):
        manager.start()
    client = TestClient(create_app(manager))
    assert client.post("/api/demo-runs").status_code == 409
    release.set()
    _wait_for_terminal(manager, first)


def test_events_are_append_only_ordered_and_exactly_schema_validated(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session_id = manager.start()
    events = _wait_for_terminal(manager, session_id)
    assert [event.sequence for event in events] == list(range(len(events)))
    assert [event.type for event in events] == [
        "session.started", "preflight.started", "preflight.completed",
        "consensus.completed", "session.completed",
    ]
    assert all(event.session_id == session_id for event in events)
    lines = manager.journal(session_id).path.read_text(encoding="utf-8").splitlines()
    assert [PresentationEvent.model_validate_json(line) for line in lines] == list(events)


def test_replay_and_last_event_id_do_not_duplicate_events(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session_id = manager.start()
    events = _wait_for_terminal(manager, session_id)
    assert [event.sequence for event in manager.journal(session_id).replay(after_sequence=1)] == [2, 3, 4]

    client = TestClient(create_app(manager))
    response = client.get(
        f"/api/demo-runs/{session_id}/events", headers={"Last-Event-ID": "2"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    ids = [int(line.removeprefix("id: ")) for line in response.text.splitlines() if line.startswith("id: ")]
    assert ids == [3, 4]
    assert len(ids) == len(set(ids))
    assert events[-1].type == "session.completed"


def test_failed_stream_has_one_terminal_failure_and_no_verdict_or_finding(tmp_path: Path) -> None:
    manager = _manager(tmp_path, _failed_runner)
    session_id = manager.start()
    events = _wait_for_terminal(manager, session_id)
    assert events[-1].type == "session.failed"
    assert events[-1].stage == "mapper"
    assert not any(event.type in {"consensus.completed", "finding.recorded"} for event in events)


def test_subscriber_can_disconnect_without_affecting_the_run(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session_id = manager.start()
    client = TestClient(create_app(manager))
    with client.stream("GET", f"/api/demo-runs/{session_id}/events") as response:
        assert response.status_code == 200
        first_id = next(line for line in response.iter_lines() if line.startswith("id: "))
        assert first_id == "id: 0"
    assert _wait_for_terminal(manager, session_id)[-1].type == "session.completed"


def test_malformed_or_partial_replay_fails_visibly(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session_id = manager.start()
    _wait_for_terminal(manager, session_id)
    journal = manager.journal(session_id)
    journal.path.write_text(journal.path.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")
    with pytest.raises(ReplayError, match="partial"):
        journal.replay()
    client = TestClient(create_app(manager))
    response = client.get(f"/api/demo-runs/{session_id}/events")
    assert response.status_code == 500
    assert "failed validation" in response.text


@pytest.mark.parametrize(
    "metadata",
    [
        {"api_key": "not-allowed"},
        {"mode": "Bearer secret-value"},
        {"mode": "sk-abcdefghijklmnopqrstuvwxyz"},
    ],
)
def test_event_metadata_allowlist_and_secret_redaction_fail_closed(
    tmp_path: Path, metadata: dict[str, object]
) -> None:
    session_id = "demo:00000000-0000-4000-8000-000000000001"
    journal = EventJournal(tmp_path, session_id, create=True)
    with pytest.raises(ValueError):
        journal.publish(
            event_type="session.started", stage="session", state="active",
            logical_role="coordinator", headline="Safe headline",
            explanation="Safe explanation", metadata=metadata,
        )
    assert not journal.path.exists()


def test_school_identity_events_accept_only_the_new_safe_metadata_shape(tmp_path: Path) -> None:
    session_id = "demo:00000000-0000-4000-8000-000000000011"
    journal = EventJournal(tmp_path, session_id, create=True)
    event = journal.publish(
        event_type="identity.student_b_discovery", stage="authorization", state="completed",
        logical_role="identity", headline="Student B submission discovery completed",
        explanation="Student B listed only the fixed synthetic submission.",
        metadata={"status_code": 200, "submission_id": "submission-student-b-001", "student": "student_b"},
        reference="scope-controller://call_app_endpoint/GET/submissions/mine",
    )
    assert event.metadata["submission_id"] == "submission-student-b-001"
    with pytest.raises(ValueError, match="disallowed field"):
        journal.publish(
            event_type="identity.student_a_retrieval", stage="authorization", state="completed",
            logical_role="identity", headline="Student A detail retrieval completed",
            explanation="Safe metadata only.",
            metadata={"record_id": "legacy-field"}, reference=None,
        )


def test_preflight_runtime_binding_metadata_is_all_or_nothing(tmp_path: Path) -> None:
    session_id = "demo:00000000-0000-4000-8000-000000000012"
    journal = EventJournal(tmp_path, session_id, create=True)
    event = journal.publish(
        event_type="preflight.completed", stage="preflight", state="completed",
        logical_role="coordinator", headline="Fixed preflight completed",
        explanation="The approved runtime binding was attested.",
        metadata={
            "role_bindings": ["mapper · fake · fixture"],
            "target_id": "crack-school-portal",
            "snapshot_sha256": "a" * 64,
            "runtime_status": "running",
            "architecture_provenance": "source-derived approved snapshot",
        },
    )
    assert event.metadata["runtime_status"] == "running"

    with pytest.raises(ValueError, match="incomplete runtime binding"):
        journal.publish(
            event_type="preflight.completed", stage="preflight", state="completed",
            logical_role="coordinator", headline="Fixed preflight completed",
            explanation="Incomplete metadata must fail closed.",
            metadata={
                "role_bindings": ["mapper · fake · fixture"],
                "target_id": "crack-school-portal",
            },
        )


def test_session_id_cannot_traverse_output_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid demo session ID"):
        EventJournal(tmp_path, "../../reports/output")


def test_journal_rejects_append_after_terminal_and_has_fixed_bound(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session_id = manager.start()
    _wait_for_terminal(manager, session_id)
    with pytest.raises(RuntimeError, match="terminal"):
        manager.journal(session_id).publish(
            event_type="preflight.started", stage="preflight", state="active",
            logical_role="coordinator", headline="Too late", explanation="Too late.",
        )


def test_persisted_event_has_no_forbidden_fields(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session_id = manager.start()
    _wait_for_terminal(manager, session_id)
    payload = json.loads(manager.journal(session_id).path.read_text(encoding="utf-8").splitlines()[0])
    forbidden = {
        "api_key", "token", "authorization", "environment", "prompt", "response",
        "chain_of_thought", "stack_trace", "database_path", "filesystem_path",
    }
    assert forbidden.isdisjoint(payload)
    assert set(payload) == {
        "session_id", "sequence", "type", "timestamp", "stage", "logical_role",
        "state", "headline", "explanation", "metadata", "reference",
    }
