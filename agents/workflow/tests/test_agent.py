from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from agents.workflow.agent import (
    WORKFLOW_APP_RULE,
    WorkflowError,
    deterministic_workflow_check,
    run_workflow,
)


ITEM_ID = "release-account-a-001"
RULE = {
    "rule_id": "approval_before_publish",
    "account": "account_a",
    "states": ["draft", "approved", "published"],
    "list_route": "/work-items/mine",
    "approve_route": "/work-items/{work_item_id}/approve",
    "publish_route": "/work-items/{work_item_id}/publish",
    "required_predecessor": "approved",
    "invalid_predecessor": "draft",
}
CONTRACT = {
    "routes": [
        {"method": "GET", "path": "/work-items/mine", "description": "List owned work items"},
        {"method": "POST", "path": "/work-items/{work_item_id}/approve", "description": "Approve a work item"},
        {"method": "POST", "path": "/work-items/{work_item_id}/publish", "description": "Publish a work item"},
    ],
    "roles": ["account-a", "account-b"],
    "assumptions": ["The workflow is synthetic and local only."],
    "workflow_rules": [RULE],
}


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def complete(self, _messages: list[dict[str, str]], **kwargs: object) -> str:
        self.requests.append(kwargs)
        return self.responses.pop(0)


def _contract_path(tmp_path: Path, contract: dict[str, object] = CONTRACT) -> Path:
    path = tmp_path / "app_contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return path


def _draft_list() -> dict[str, object]:
    return {
        "status_code": 200,
        "body": {
            "work_items": [
                {"id": ITEM_ID, "owner_account_id": "account-a", "state": "draft"}
            ]
        },
    }


def test_observed_draft_publish_submits_one_unverified_workflow_hypothesis(tmp_path: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    submitted: list[tuple[str, str, str, str]] = []
    client = FakeClient([
        json.dumps({"workflow_rule_id": "approval_before_publish"}),
        json.dumps({"concise_claim": "Draft work item publishes without approval.", "expected_evidence": "Account A receives a draft-to-published result."}),
    ])

    def call(method: str, path: str, token: str) -> dict[str, object]:
        calls.append((method, path, token))
        if method == "GET":
            return _draft_list()
        return {"status_code": 200, "body": {"id": ITEM_ID, "previous_state": "draft", "state": "published"}}

    result = run_workflow(
        client=client,
        contract_path=_contract_path(tmp_path),
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *args: submitted.append(args) or "workflow-hypothesis",
        run_recorder=lambda **_kwargs: None,
    )

    assert calls == [
        ("GET", "/work-items/mine", "token-account-a-fixed"),
        ("POST", f"/work-items/{ITEM_ID}/publish", "token-account-a-fixed"),
    ]
    assert result.hypothesis_ids == ["workflow-hypothesis"]
    assert submitted[0][1] == WORKFLOW_APP_RULE
    assert client.requests == [
        {"response_format": {"type": "json_object"}},
        {"response_format": {"type": "json_object"}},
    ]


@pytest.mark.parametrize(
    "publish_response",
    [
        {"status_code": 409, "body": {"detail": "Approval required"}},
        {"status_code": 200, "body": {"id": ITEM_ID, "previous_state": "approved", "state": "published"}},
        {"status_code": 200, "body": {"id": "other", "previous_state": "draft", "state": "published"}},
    ],
)
def test_valid_enforcement_or_incomplete_evidence_submits_no_hypothesis(
    tmp_path: Path, publish_response: dict[str, object]
) -> None:
    submitted: list[tuple[object, ...]] = []

    def call(method: str, _path: str, _token: str) -> dict[str, object]:
        return _draft_list() if method == "GET" else publish_response

    result = run_workflow(
        client=FakeClient([json.dumps({"workflow_rule_id": "approval_before_publish"})]),
        contract_path=_contract_path(tmp_path),
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *args: submitted.append(args) or "unexpected",
        run_recorder=lambda **_kwargs: None,
    )

    assert result.hypothesis_ids == []
    assert submitted == []


@pytest.mark.parametrize(
    "plan",
    [
        {"workflow_rule_id": "approval_before_publish", "path": "/anything"},
        {"workflow_rule_id": "other_rule"},
        {"workflow_rule_id": "approval_before_publish", "account": "account_b"},
    ],
)
def test_out_of_contract_model_plan_fails_closed_before_any_call(tmp_path: Path, plan: dict[str, object]) -> None:
    calls: list[tuple[str, str, str]] = []

    with pytest.raises(WorkflowError):
        run_workflow(
            client=FakeClient([json.dumps(plan)]),
            contract_path=_contract_path(tmp_path),
            endpoint_caller=lambda *args: calls.append(args) or _draft_list(),
            evidence_recorder=lambda **_kwargs: None,
            hypothesis_submitter=lambda *_args: "unexpected",
            run_recorder=lambda **_kwargs: None,
        )

    assert calls == []


def test_missing_or_incomplete_workflow_contract_fails_closed_before_any_call(tmp_path: Path) -> None:
    calls: list[tuple[object, ...]] = []
    no_rule = {key: value for key, value in CONTRACT.items() if key != "workflow_rules"}

    with pytest.raises(WorkflowError, match="exactly one bounded workflow rule"):
        run_workflow(
            client=FakeClient([json.dumps({"workflow_rule_id": "approval_before_publish"})]),
            contract_path=_contract_path(tmp_path, no_rule),
            endpoint_caller=lambda *args: calls.append(args) or _draft_list(),
            evidence_recorder=lambda **_kwargs: None,
            hypothesis_submitter=lambda *_args: "unexpected",
            run_recorder=lambda **_kwargs: None,
        )

    assert calls == []


def test_provider_failure_has_no_hypothesis_or_status_side_effect(tmp_path: Path) -> None:
    submitted: list[tuple[object, ...]] = []
    runs: list[dict[str, object]] = []

    class FailingClient(FakeClient):
        def complete(self, *_args: object, **_kwargs: object) -> str:
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        run_workflow(
            client=FailingClient([]),
            contract_path=_contract_path(tmp_path),
            endpoint_caller=lambda *_args: _draft_list(),
            evidence_recorder=lambda **_kwargs: None,
            hypothesis_submitter=lambda *args: submitted.append(args) or "unexpected",
            run_recorder=lambda **kwargs: runs.append(kwargs),
        )

    assert submitted == []
    assert runs[-1]["status"] == "failed"


def test_code_owned_predicate_requires_exact_draft_to_published_transition() -> None:
    satisfied, _reason = deterministic_workflow_check(
        _draft_list(),
        {"status_code": 200, "body": {"id": ITEM_ID, "previous_state": "draft", "state": "published"}},
        ITEM_ID,
    )
    assert satisfied is True

    rejected, _reason = deterministic_workflow_check(
        _draft_list(),
        {"status_code": 200, "body": {"id": ITEM_ID, "previous_state": "approved", "state": "published"}},
        ITEM_ID,
    )
    assert rejected is False


def test_agent_has_no_direct_network_database_shell_or_environment_access() -> None:
    source = inspect.getsource(__import__("agents.workflow.agent", fromlist=["run_workflow"]))
    forbidden = ("http.client", "requests.", "sqlite3", "subprocess", "os.environ", "socket")
    assert all(value not in source for value in forbidden)
