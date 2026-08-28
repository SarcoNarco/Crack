from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from agents.verifier.agent import (
    ExecutedStep,
    VerifierError,
    deterministic_boundary_check,
    run_verifier,
)
from agents.workflow.agent import WORKFLOW_APP_RULE


AUTH_ID = "hypothesis-student-boundary"
AUTH = {
    "id": AUTH_ID,
    "submitted_by_run": "identity:one",
    "affected_app_rule": "GET /submissions/{submission_id}/grade must enforce student ownership",
    "concise_claim": "Student A can read Student B's submission grade detail.",
    "expected_evidence": (
        "Student B discovers an exact submission and Student A receives its grade detail."
    ),
    "verification_status": "unverified",
    "verifier_run_id": None,
}
AUTH_PLAN = json.dumps(
    {
        "steps": [
            {"method": "GET", "path": "/submissions/mine", "role": "student_b"},
            {
                "method": "GET",
                "path": "/submissions/{submission_id}/grade",
                "role": "student_a",
            },
        ]
    }
)
WORKFLOW = {
    "id": "hypothesis-grade-workflow",
    "submitted_by_run": "workflow:one",
    "affected_app_rule": WORKFLOW_APP_RULE,
    "concise_claim": "A draft grade can be published without review.",
    "expected_evidence": "Teacher lists a draft grade then receives a published result.",
    "verification_status": "unverified",
    "verifier_run_id": None,
}
WORKFLOW_PLAN = json.dumps(
    {"steps": [{"operation": "list_teacher_grades"}, {"operation": "publish_grade"}]}
)


class FakeClient:
    def __init__(self, role: str, response: str, trace: list[str]) -> None:
        self.role = role
        self.response = response
        self.trace = trace
        self.requests: list[dict[str, object]] = []

    def complete(self, _messages: list[dict[str, str]], **kwargs: object) -> str:
        self.trace.append(f"plan:{self.role}")
        self.requests.append(kwargs)
        return self.response


class FailingClient(FakeClient):
    def complete(self, _messages: list[dict[str, str]], **kwargs: object) -> str:
        self.trace.append(f"plan:{self.role}")
        self.requests.append(kwargs)
        raise RuntimeError("provider unavailable")


def _step(role: str, body: object, path: str) -> ExecutedStep:
    return ExecutedStep(
        "GET",
        path,
        path,
        role,
        True,
        {"status_code": 200, "body": body},
        "executed",
        "ledger://test",
    )


def test_exact_discovered_student_b_submission_returned_to_student_a_succeeds() -> None:
    discovery = _step(
        "student_b",
        {
            "submissions": [
                {
                    "submission_id": "submission-student-b-001",
                    "student_id": "student-b",
                }
            ]
        },
        "/submissions/mine",
    )
    detail = _step(
        "student_a",
        {
            "submission_id": "submission-student-b-001",
            "student_id": "student-b",
            "grade_id": "grade-student-b-001",
        },
        "/submissions/submission-student-b-001/grade",
    )

    assert deterministic_boundary_check((discovery, detail))[0] is True


@pytest.mark.parametrize(
    "detail",
    [
        {
            "submission_id": "other",
            "student_id": "student-b",
            "grade_id": "grade-student-b-001",
        },
        {
            "submission_id": "submission-student-b-001",
            "student_id": "student-a",
            "grade_id": "grade-student-b-001",
        },
        {"submission_id": "submission-student-b-001", "student_id": "student-b"},
    ],
)
def test_predicate_rejects_wrong_id_owner_or_missing_grade(detail: dict[str, object]) -> None:
    discovery = _step(
        "student_b",
        {
            "submissions": [
                {
                    "submission_id": "submission-student-b-001",
                    "student_id": "student-b",
                }
            ]
        },
        "/submissions/mine",
    )
    response = _step("student_a", detail, "/submissions/submission-student-b-001/grade")

    assert deterministic_boundary_check((discovery, response))[0] is False


def _run(
    successes: tuple[bool, bool],
    progress: Callable[..., None] | None = None,
) -> tuple[object, dict[str, object]]:
    trace: list[str] = []
    evidence: list[dict[str, object]] = []
    statuses: list[tuple[str, str, str]] = []
    findings: list[tuple[str, str, str, str, str]] = []
    runs: list[dict[str, object]] = []
    reset_count = 0

    def reset() -> str:
        nonlocal reset_count
        reset_count += 1
        trace.append(f"reset:{reset_count}")
        return f"reset:unique-{reset_count}:state-sha256:identical"

    def call(method: str, path: str, token: str) -> dict[str, object]:
        trace.append(f"call:{reset_count}:{method}:{path}:{token}")
        if path == "/submissions/mine":
            assert token == "token-student-b-fixed"
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
        assert token == "token-student-a-fixed"
        assert path == "/submissions/submission-student-b-001/grade"
        return {
            "status_code": 200 if successes[reset_count - 1] else 403,
            "body": {
                "submission_id": "submission-student-b-001",
                "student_id": "student-b",
                "grade_id": "grade-student-b-001",
            },
        }

    result = run_verifier(
        AUTH_ID,
        client_a=FakeClient("verifier_a", AUTH_PLAN, trace),
        client_b=FakeClient("verifier_b", AUTH_PLAN, trace),
        hypothesis_reader=lambda _id: AUTH,
        resetter=reset,
        endpoint_caller=call,
        evidence_recorder=lambda **kwargs: evidence.append(kwargs),
        status_updater=lambda *args: statuses.append(args),
        finding_recorder=lambda *args: findings.append(args) or "finding-1",
        run_recorder=lambda **kwargs: runs.append(kwargs),
        progress=progress,
    )
    return result, {
        "trace": trace,
        "evidence": evidence,
        "statuses": statuses,
        "findings": findings,
        "runs": runs,
        "reset_count": reset_count,
    }


@pytest.mark.parametrize(
    ("successes", "verdict"),
    [
        ((True, True), "verified"),
        ((False, False), "unverified"),
        ((True, False), "inconclusive"),
    ],
)
def test_two_clean_resets_and_code_owned_verdict(
    successes: tuple[bool, bool],
    verdict: str,
) -> None:
    result, context = _run(successes)

    assert result.verdict == verdict
    assert context["reset_count"] == 2
    assert result.attempts[0].snapshot_id != result.attempts[1].snapshot_id
    assert {
        attempt.snapshot_id.rsplit(":state-sha256:", 1)[1]
        for attempt in result.attempts
    } == {"identical"}
    assert (
        context["trace"].index("reset:1")
        < context["trace"].index("plan:verifier_a")
        < context["trace"].index("reset:2")
        < context["trace"].index("plan:verifier_b")
    )
    assert (len(context["findings"]) == 1) is (verdict == "verified")
    assert context["statuses"][0][1] == verdict
    assert context["runs"][-1]["status"] == "completed"
    if verdict == "verified":
        assert "student ownership" in context["findings"][0][4]


def test_verifier_progress_follows_sequential_boundaries_and_is_presentation_only() -> None:
    events: list[str] = []

    def observer(**event: object) -> None:
        event_type = str(event["event_type"])
        events.append(event_type)
        if event_type == "verifier_a.call_recorded":
            raise RuntimeError("presentation unavailable")

    result, _context = _run((True, True), progress=observer)

    assert result.verdict == "verified"
    expected_order = [
        "verifier_a.activated",
        "verifier_a.reset_completed",
        "verifier_a.plan_validated",
        "verifier_a.check_completed",
        "verifier_a.completed",
        "verifier_b.activated",
        "verifier_b.reset_completed",
        "verifier_b.plan_validated",
        "verifier_b.check_completed",
        "verifier_b.completed",
        "consensus.started",
        "consensus.completed",
        "finding.recorded",
    ]
    assert [events.index(event_type) for event_type in expected_order] == sorted(
        events.index(event_type) for event_type in expected_order
    )
    assert events.count("verifier_a.call_recorded") == 2
    assert events.count("verifier_b.call_recorded") == 2


@pytest.mark.parametrize(
    "client",
    [
        FailingClient("verifier_a", AUTH_PLAN, []),
        FakeClient("verifier_a", "not valid structured JSON", []),
    ],
    ids=["provider-failure", "malformed-output"],
)
def test_verifier_provider_or_schema_failure_fails_before_verdict_or_finding(
    client: FakeClient,
) -> None:
    endpoint_calls: list[tuple[object, ...]] = []
    statuses: list[tuple[object, ...]] = []
    findings: list[tuple[object, ...]] = []
    runs: list[dict[str, object]] = []
    resets: list[str] = []

    def reset() -> str:
        reset_id = f"reset:{len(resets) + 1}:state-sha256:same"
        resets.append(reset_id)
        return reset_id

    with pytest.raises((RuntimeError, VerifierError)):
        run_verifier(
            AUTH_ID,
            client_a=client,
            client_b=FakeClient("verifier_b", AUTH_PLAN, []),
            hypothesis_reader=lambda _id: AUTH,
            resetter=reset,
            endpoint_caller=lambda *args: endpoint_calls.append(args) or {},
            evidence_recorder=lambda **_kwargs: None,
            status_updater=lambda *args: statuses.append(args),
            finding_recorder=lambda *args: findings.append(args) or "unexpected",
            run_recorder=lambda **kwargs: runs.append(kwargs),
        )

    assert len(resets) == 1
    assert endpoint_calls == []
    assert statuses == []
    assert findings == []
    assert runs[-1]["status"] == "failed"


def test_unresolved_submission_placeholder_is_not_executed() -> None:
    endpoint_calls: list[tuple[object, ...]] = []
    placeholder_only = json.dumps(
        {
            "steps": [
                {
                    "method": "GET",
                    "path": "/submissions/{submission_id}/grade",
                    "role": "student_a",
                }
            ]
        }
    )

    result = run_verifier(
        AUTH_ID,
        client_a=FakeClient("verifier_a", placeholder_only, []),
        client_b=FakeClient("verifier_b", placeholder_only, []),
        hypothesis_reader=lambda _id: AUTH,
        resetter=lambda: "reset:placeholder:state-sha256:same",
        endpoint_caller=lambda *args: endpoint_calls.append(args) or {},
        evidence_recorder=lambda **_kwargs: None,
        status_updater=lambda *_args: None,
        finding_recorder=lambda *_args: "unexpected",
        run_recorder=lambda **_kwargs: None,
    )

    assert result.verdict == "unverified"
    assert endpoint_calls == []
    assert all(
        not step.executed
        for attempt in result.attempts
        for step in attempt.executed_steps
    )


def test_guessed_student_b_detail_path_cannot_substitute_for_normal_discovery() -> None:
    guessed_path = "/submissions/submission-student-b-001/grade"
    guessed_detail_plan = json.dumps(
        {
            "steps": [
                {"method": "GET", "path": guessed_path, "role": "student_b"},
                {"method": "GET", "path": guessed_path, "role": "student_a"},
            ]
        }
    )
    statuses: list[tuple[object, ...]] = []
    findings: list[tuple[object, ...]] = []

    def call(method: str, path: str, token: str) -> dict[str, object]:
        assert method == "GET"
        assert path == guessed_path
        assert token in {"token-student-a-fixed", "token-student-b-fixed"}
        return {
            "status_code": 200,
            "body": {
                "submission_id": "submission-student-b-001",
                "student_id": "student-b",
                "grade_id": "grade-student-b-001",
            },
        }

    result = run_verifier(
        AUTH_ID,
        client_a=FakeClient("verifier_a", guessed_detail_plan, []),
        client_b=FakeClient("verifier_b", guessed_detail_plan, []),
        hypothesis_reader=lambda _id: AUTH,
        resetter=lambda: "reset:guessed-detail:state-sha256:same",
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        status_updater=lambda *args: statuses.append(args),
        finding_recorder=lambda *args: findings.append(args) or "unexpected",
        run_recorder=lambda **_kwargs: None,
    )

    assert result.verdict == "unverified"
    assert result.finding_id is None
    assert statuses[0][1] == "unverified"
    assert findings == []


def test_workflow_predicate_binds_teacher_grade_id_and_states() -> None:
    reset_count = 0

    def reset() -> str:
        nonlocal reset_count
        reset_count += 1
        return f"reset:grade-{reset_count}:state-sha256:same"

    def call(method: str, path: str, token: str) -> dict[str, object]:
        assert token == "token-teacher-fixed"
        if method == "GET":
            assert path == "/grades/mine"
            return {
                "status_code": 200,
                "body": {
                    "grades": [
                        {
                            "grade_id": "grade-student-a-001",
                            "teacher_id": "teacher-001",
                            "state": "draft",
                        }
                    ]
                },
            }
        assert path == "/grades/grade-student-a-001/publish"
        return {
            "status_code": 200,
            "body": {
                "grade_id": "grade-student-a-001",
                "previous_state": "draft",
                "state": "published",
            },
        }

    result = run_verifier(
        WORKFLOW["id"],
        client_a=FakeClient("verifier_a", WORKFLOW_PLAN, []),
        client_b=FakeClient("verifier_b", WORKFLOW_PLAN, []),
        hypothesis_reader=lambda _id: WORKFLOW,
        resetter=reset,
        endpoint_caller=call,
        evidence_recorder=lambda **_kwargs: None,
        status_updater=lambda *_args: None,
        finding_recorder=lambda *_args: "grade-finding",
        run_recorder=lambda **_kwargs: None,
    )

    assert result.verdict == "verified"
    assert all(
        step.role == "teacher"
        for attempt in result.attempts
        for step in attempt.executed_steps
    )
