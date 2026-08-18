from __future__ import annotations

import json
from pathlib import Path

from agents.identity.agent import run_identity


CONTRACT = {
    "routes": [
        {"method": "GET", "path": "/health", "description": "Health check"},
        {"method": "GET", "path": "/records/mine", "description": "My records"},
        {"method": "GET", "path": "/records/{record_id}", "description": "Read one record"},
        {"method": "PUT", "path": "/records/{record_id}", "description": "Update one record"},
    ],
    "roles": ["account-a", "account-b"],
    "assumptions": ["Accounts have records."],
}


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def complete(self, _messages: list[dict[str, str]], **kwargs: object) -> str:
        self.requests.append(kwargs)
        return self.responses.pop(0)


def _contract_path(tmp_path: Path) -> Path:
    path = tmp_path / "app_contract.json"
    path.write_text(json.dumps(CONTRACT), encoding="utf-8")
    return path


def _plan() -> str:
    return json.dumps({"boundary_route": "/records/{record_id}"})


def _account_b_records() -> dict[str, object]:
    return {
        "status_code": 200,
        "body": {"records": [{"id": "note-account-b-001", "owner_account_id": "account-b"}]},
    }


def test_no_boundary_violation_does_not_submit_hypothesis(tmp_path: Path) -> None:
    client = FakeClient([_plan()])
    calls: list[tuple[str, str, str]] = []
    submitted: list[tuple[str, str, str, str]] = []

    def call(method: str, path: str, token: str) -> dict[str, object]:
        calls.append((method, path, token))
        if path == "/records/mine":
            return _account_b_records()
        return {"status_code": 404, "body": {"detail": "Record not found"}}

    result = run_identity(
        client=client, contract_path=_contract_path(tmp_path), endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *args: submitted.append(args) or "unexpected",
        run_recorder=lambda **_kwargs: None,
    )

    assert calls == [
        ("GET", "/records/mine", "token-account-b-fixed"),
        ("GET", "/records/note-account-b-001", "token-account-a-fixed"),
    ]
    assert result.hypothesis_ids == []
    assert submitted == []


def test_boundary_violation_submits_llm_worded_hypothesis(tmp_path: Path) -> None:
    claim = "Account A can read Account B's record via GET /records/{record_id} without ownership check"
    client = FakeClient([
        _plan(),
        json.dumps({
            "concise_claim": claim,
            "expected_evidence": "Account B GET /records/mine reveals its record ID; Account A GET of that ID returns Account B's record.",
        }),
    ])
    calls: list[tuple[str, str, str]] = []
    submitted: list[tuple[str, str, str, str]] = []

    def call(method: str, path: str, token: str) -> dict[str, object]:
        calls.append((method, path, token))
        if path == "/records/mine":
            return _account_b_records()
        return {
            "status_code": 200,
            "body": {"id": "note-account-b-001", "owner_account_id": "account-b"},
        }

    result = run_identity(
        client=client, contract_path=_contract_path(tmp_path), endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *args: submitted.append(args) or "hyp-123",
        run_recorder=lambda **_kwargs: None,
    )

    assert calls == [
        ("GET", "/records/mine", "token-account-b-fixed"),
        ("GET", "/records/note-account-b-001", "token-account-a-fixed"),
    ]
    assert result.hypothesis_ids == ["hyp-123"]
    assert submitted[0][1:3] == ("GET /records/{record_id} must enforce record ownership", claim)
    assert client.requests == [
        {"response_format": {"type": "json_object"}},
        {"response_format": {"type": "json_object"}},
    ]


def test_identity_agent_never_exceeds_two_endpoint_calls(tmp_path: Path) -> None:
    client = FakeClient([_plan()])
    calls: list[tuple[str, str, str]] = []

    def call(method: str, path: str, token: str) -> dict[str, object]:
        calls.append((method, path, token))
        return _account_b_records() if path == "/records/mine" else {"status_code": 403, "body": {}}

    run_identity(
        client=client, contract_path=_contract_path(tmp_path), endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *args: "unexpected", run_recorder=lambda **_kwargs: None,
    )

    assert calls == [
        ("GET", "/records/mine", "token-account-b-fixed"),
        ("GET", "/records/note-account-b-001", "token-account-a-fixed"),
    ]
    assert all(method == "GET" and path != "/login" for method, path, _ in calls)


def test_progress_observer_failure_does_not_change_identity_result(tmp_path: Path) -> None:
    client = FakeClient([
        _plan(),
        json.dumps({
            "concise_claim": "Account A can read Account B's record",
            "expected_evidence": "The exact Account B record is returned to Account A.",
        }),
    ])

    def call(_method: str, path: str, _token: str) -> dict[str, object]:
        if path == "/records/mine":
            return _account_b_records()
        return {
            "status_code": 200,
            "body": {"id": "note-account-b-001", "owner_account_id": "account-b"},
        }

    def broken_observer(**_event: object) -> None:
        raise RuntimeError("presentation unavailable")

    result = run_identity(
        client=client,
        contract_path=_contract_path(tmp_path),
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *_args: "hyp-123",
        run_recorder=lambda **_kwargs: None,
        progress=broken_observer,
    )

    assert result.hypothesis_ids == ["hyp-123"]
