from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.identity.agent import IdentityError, run_identity


CONTRACT = {
    "routes": [
        {
            "method": "GET",
            "path": "/submissions/mine",
            "description": "My submissions",
        },
        {
            "method": "GET",
            "path": "/submissions/{submission_id}/grade",
            "description": "Read a submission grade",
        },
        {
            "method": "POST",
            "path": "/grades/{grade_id}/publish",
            "description": "Publish grade",
        },
    ],
    "roles": ["Teacher", "Student A", "Student B"],
    "assumptions": ["Synthetic portal."],
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


def _student_b_submissions() -> dict[str, object]:
    return {
        "status_code": 200,
        "body": {
            "submissions": [
                {
                    "submission_id": "submission-student-b-001",
                    "student_id": "student-b",
                }
            ]
        },
    }


def _detail_success() -> dict[str, object]:
    return {
        "status_code": 200,
        "body": {
            "submission_id": "submission-student-b-001",
            "student_id": "student-b",
            "grade_id": "grade-student-b-001",
        },
    }


def _boundary_plan() -> str:
    return json.dumps({"boundary_route": "/submissions/{submission_id}/grade"})


def test_exact_student_b_submission_returned_to_student_a_submits_one_hypothesis(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str, str]] = []
    submitted: list[tuple[str, str, str, str]] = []
    client = FakeClient(
        [
            _boundary_plan(),
            json.dumps(
                {
                    "concise_claim": "Student A can read Student B's grade detail.",
                    "expected_evidence": (
                        "Student B lists a submission and Student A receives its exact detail."
                    ),
                }
            ),
        ]
    )

    def call(method: str, path: str, token: str) -> dict[str, object]:
        calls.append((method, path, token))
        return _student_b_submissions() if path == "/submissions/mine" else _detail_success()

    result = run_identity(
        client=client,
        contract_path=_contract_path(tmp_path),
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *args: submitted.append(args) or "identity-hypothesis",
        run_recorder=lambda **_kwargs: None,
    )

    assert calls == [
        ("GET", "/submissions/mine", "token-student-b-fixed"),
        (
            "GET",
            "/submissions/submission-student-b-001/grade",
            "token-student-a-fixed",
        ),
    ]
    assert result.hypothesis_ids == ["identity-hypothesis"]
    assert (
        submitted[0][1]
        == "GET /submissions/{submission_id}/grade must enforce student ownership"
    )
    assert client.requests == [
        {"response_format": {"type": "json_object"}},
        {"response_format": {"type": "json_object"}},
    ]


@pytest.mark.parametrize(
    "detail",
    [
        {"status_code": 403, "body": {}},
        {
            "status_code": 200,
            "body": {
                "submission_id": "other",
                "student_id": "student-b",
                "grade_id": "grade-student-b-001",
            },
        },
        {
            "status_code": 200,
            "body": {
                "submission_id": "submission-student-b-001",
                "student_id": "student-a",
                "grade_id": "grade-student-b-001",
            },
        },
    ],
)
def test_incomplete_or_enforced_detail_does_not_submit(
    tmp_path: Path,
    detail: dict[str, object],
) -> None:
    submitted: list[tuple[object, ...]] = []

    def call(_method: str, path: str, _token: str) -> dict[str, object]:
        return _student_b_submissions() if path == "/submissions/mine" else detail

    result = run_identity(
        client=FakeClient([_boundary_plan()]),
        contract_path=_contract_path(tmp_path),
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *args: submitted.append(args) or "unexpected",
        run_recorder=lambda **_kwargs: None,
    )

    assert result.hypothesis_ids == []
    assert submitted == []


def test_identity_never_exceeds_two_fixed_get_calls(tmp_path: Path) -> None:
    calls: list[tuple[str, str, str]] = []

    def call(method: str, path: str, token: str) -> dict[str, object]:
        calls.append((method, path, token))
        return (
            _student_b_submissions()
            if path == "/submissions/mine"
            else {"status_code": 403, "body": {}}
        )

    run_identity(
        client=FakeClient([_boundary_plan()]),
        contract_path=_contract_path(tmp_path),
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *_args: "unexpected",
        run_recorder=lambda **_kwargs: None,
    )

    assert len(calls) == 2
    assert all(method == "GET" for method, _path, _token in calls)
    assert all(path.startswith("/submissions/") for _method, path, _token in calls)


def test_progress_observer_failure_does_not_change_identity_result(tmp_path: Path) -> None:
    def call(_method: str, path: str, _token: str) -> dict[str, object]:
        return _student_b_submissions() if path == "/submissions/mine" else _detail_success()

    def broken_observer(**_event: object) -> None:
        raise RuntimeError("presentation unavailable")

    result = run_identity(
        client=FakeClient(
            [
                _boundary_plan(),
                json.dumps(
                    {
                        "concise_claim": "Student A can read Student B's grade detail.",
                        "expected_evidence": "The exact Student B submission is returned to Student A.",
                    }
                ),
            ]
        ),
        contract_path=_contract_path(tmp_path),
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        hypothesis_submitter=lambda *_args: "identity-hypothesis",
        run_recorder=lambda **_kwargs: None,
        progress=broken_observer,
    )

    assert result.hypothesis_ids == ["identity-hypothesis"]


def test_contract_or_plan_outside_the_fixed_submission_route_fails_closed(
    tmp_path: Path,
) -> None:
    calls: list[tuple[object, ...]] = []

    with pytest.raises(IdentityError, match="Student B discovery"):
        run_identity(
            client=FakeClient([json.dumps({"boundary_route": "/outside/{submission_id}"})]),
            contract_path=_contract_path(tmp_path),
            endpoint_caller=lambda *args: calls.append(args) or _student_b_submissions(),
            evidence_recorder=lambda **_kwargs: None,
            hypothesis_submitter=lambda *_args: "unexpected",
            run_recorder=lambda **_kwargs: None,
        )

    bad_contract = {
        **CONTRACT,
        "routes": [
            route
            for route in CONTRACT["routes"]
            if route["path"] != "/submissions/{submission_id}/grade"
        ],
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad_contract), encoding="utf-8")
    with pytest.raises(IdentityError, match="Student B discovery"):
        run_identity(
            client=FakeClient([_boundary_plan()]),
            contract_path=path,
            endpoint_caller=lambda *args: calls.append(args) or _student_b_submissions(),
            evidence_recorder=lambda **_kwargs: None,
            hypothesis_submitter=lambda *_args: "unexpected",
            run_recorder=lambda **_kwargs: None,
        )

    assert calls == []
