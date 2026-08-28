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


GRADE_ID = "grade-student-a-001"
RULE = {
    "rule_id": "review_before_publish",
    "account": "teacher",
    "states": ["draft", "reviewed", "published"],
    "list_route": "/grades/mine",
    "review_route": "/grades/{grade_id}/review",
    "publish_route": "/grades/{grade_id}/publish",
    "required_predecessor": "reviewed",
    "invalid_predecessor": "draft",
}
CONTRACT = {
    "routes": [
        {
            "method": "GET",
            "path": "/grades/mine",
            "description": "List Teacher grades",
        },
        {
            "method": "POST",
            "path": "/grades/{grade_id}/review",
            "description": "Review grade",
        },
        {
            "method": "POST",
            "path": "/grades/{grade_id}/publish",
            "description": "Publish grade",
        },
    ],
    "roles": ["Teacher", "Student A", "Student B"],
    "assumptions": ["Synthetic portal."],
    "workflow_rules": [RULE],
}


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def complete(self, _messages: list[dict[str, str]], **kwargs: object) -> str:
        self.requests.append(kwargs)
        return self.responses.pop(0)


class FailingClient(FakeClient):
    def complete(self, *_args: object, **_kwargs: object) -> str:
        raise RuntimeError("provider unavailable")


def _contract_path(tmp_path: Path, contract: dict[str, object] = CONTRACT) -> Path:
    path = tmp_path / "app_contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return path


def _draft_list() -> dict[str, object]:
    return {
        "status_code": 200,
        "body": {
            "grades": [
                {
                    "grade_id": GRADE_ID,
                    "teacher_id": "teacher-001",
                    "state": "draft",
                }
            ]
        },
    }


def test_draft_grade_publish_submits_one_unverified_workflow_hypothesis(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str, str]] = []
    submitted: list[tuple[str, str, str, str]] = []
    client = FakeClient(
        [
            json.dumps({"workflow_rule_id": "review_before_publish"}),
            json.dumps(
                {
                    "concise_claim": "Draft grade publishes without review.",
                    "expected_evidence": "Teacher receives a draft-to-published grade result.",
                }
            ),
        ]
    )

    def call(method: str, path: str, token: str) -> dict[str, object]:
        calls.append((method, path, token))
        if method == "GET":
            return _draft_list()
        return {
            "status_code": 200,
            "body": {
                "grade_id": GRADE_ID,
                "previous_state": "draft",
                "state": "published",
            },
        }

    result = run_workflow(
        client=client,
        contract_path=_contract_path(tmp_path),
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *args: submitted.append(args) or "workflow-hypothesis",
        run_recorder=lambda **_kwargs: None,
    )

    assert calls == [
        ("GET", "/grades/mine", "token-teacher-fixed"),
        ("POST", f"/grades/{GRADE_ID}/publish", "token-teacher-fixed"),
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
        {"status_code": 409, "body": {"detail": "Review required"}},
        {
            "status_code": 200,
            "body": {
                "grade_id": GRADE_ID,
                "previous_state": "reviewed",
                "state": "published",
            },
        },
        {
            "status_code": 200,
            "body": {
                "grade_id": "other",
                "previous_state": "draft",
                "state": "published",
            },
        },
    ],
)
def test_valid_enforcement_or_incomplete_evidence_submits_no_hypothesis(
    tmp_path: Path,
    publish_response: dict[str, object],
) -> None:
    submitted: list[tuple[object, ...]] = []
    result = run_workflow(
        client=FakeClient([json.dumps({"workflow_rule_id": "review_before_publish"})]),
        contract_path=_contract_path(tmp_path),
        endpoint_caller=lambda method, *_args: (
            _draft_list() if method == "GET" else publish_response
        ),
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *args: submitted.append(args) or "unexpected",
        run_recorder=lambda **_kwargs: None,
    )

    assert result.hypothesis_ids == []
    assert submitted == []


@pytest.mark.parametrize(
    "plan",
    [
        {"workflow_rule_id": "review_before_publish", "path": "/anything"},
        {"workflow_rule_id": "other_rule"},
        {"workflow_rule_id": "review_before_publish", "role": "student_a"},
    ],
)
def test_out_of_contract_workflow_plans_fail_before_app_calls(
    tmp_path: Path,
    plan: dict[str, object],
) -> None:
    calls: list[tuple[object, ...]] = []

    with pytest.raises(WorkflowError, match="workflow-agent schema"):
        run_workflow(
            client=FakeClient([json.dumps(plan)]),
            contract_path=_contract_path(tmp_path),
            endpoint_caller=lambda *args: calls.append(args) or _draft_list(),
            evidence_recorder=lambda **_kwargs: None,
            hypothesis_submitter=lambda *_args: "unexpected",
            run_recorder=lambda **_kwargs: None,
        )

    assert calls == []


@pytest.mark.parametrize(
    "contract",
    [
        {key: value for key, value in CONTRACT.items() if key != "workflow_rules"},
        {**CONTRACT, "workflow_rules": [{**RULE, "publish_route": "/outside/{grade_id}"}]},
        {
            **CONTRACT,
            "routes": [
                route
                for route in CONTRACT["routes"]
                if route["path"] != "/grades/{grade_id}/review"
            ],
        },
    ],
)
def test_out_of_contract_workflow_rules_and_routes_fail_before_app_calls(
    tmp_path: Path,
    contract: dict[str, object],
) -> None:
    calls: list[tuple[object, ...]] = []

    with pytest.raises(WorkflowError):
        run_workflow(
            client=FakeClient([json.dumps({"workflow_rule_id": "review_before_publish"})]),
            contract_path=_contract_path(tmp_path, contract),
            endpoint_caller=lambda *args: calls.append(args) or _draft_list(),
            evidence_recorder=lambda **_kwargs: None,
            hypothesis_submitter=lambda *_args: "unexpected",
            run_recorder=lambda **_kwargs: None,
        )

    assert calls == []


@pytest.mark.parametrize(
    "client",
    [FailingClient([]), FakeClient(["not valid structured JSON"])],
    ids=["provider-failure", "malformed-output"],
)
def test_provider_or_schema_failure_has_no_side_effects_or_endpoint_calls(
    tmp_path: Path,
    client: FakeClient,
) -> None:
    calls: list[tuple[object, ...]] = []
    submitted: list[tuple[object, ...]] = []
    runs: list[dict[str, object]] = []

    with pytest.raises((RuntimeError, WorkflowError)):
        run_workflow(
            client=client,
            contract_path=_contract_path(tmp_path),
            endpoint_caller=lambda *args: calls.append(args) or _draft_list(),
            evidence_recorder=lambda **_kwargs: None,
            hypothesis_submitter=lambda *args: submitted.append(args) or "unexpected",
            run_recorder=lambda **kwargs: runs.append(kwargs),
        )

    assert calls == []
    assert submitted == []
    assert runs[-1]["status"] == "failed"


def test_predicate_binds_exact_grade_owner_and_states() -> None:
    assert deterministic_workflow_check(
        _draft_list(),
        {
            "status_code": 200,
            "body": {
                "grade_id": GRADE_ID,
                "previous_state": "draft",
                "state": "published",
            },
        },
        GRADE_ID,
    )[0] is True
    assert deterministic_workflow_check(
        {
            "status_code": 200,
            "body": {
                "grades": [
                    {"grade_id": GRADE_ID, "teacher_id": "other", "state": "draft"}
                ]
            },
        },
        {
            "status_code": 200,
            "body": {
                "grade_id": GRADE_ID,
                "previous_state": "draft",
                "state": "published",
            },
        },
        GRADE_ID,
    )[0] is False


def test_workflow_has_no_direct_network_database_shell_or_environment_capability() -> None:
    source = inspect.getsource(__import__("agents.workflow.agent", fromlist=["run_workflow"]))
    forbidden = (
        "http.client",
        "requests.",
        "sqlite3",
        "subprocess",
        "os.environ",
        "os.getenv",
        "socket",
    )

    assert all(value not in source for value in forbidden)
    assert "target" not in inspect.signature(run_workflow).parameters
    assert "status_updater" not in inspect.signature(run_workflow).parameters
