from __future__ import annotations

import json

import pytest

from agents.verifier.agent import ExecutedStep, deterministic_boundary_check, run_verifier


HYPOTHESIS_ID = "hypothesis-account-boundary"
HYPOTHESIS = {
    "id": HYPOTHESIS_ID,
    "submitted_by_run": "identity:one",
    "affected_app_rule": "GET /records/{record_id} enforces ownership",
    "concise_claim": "Account A can read Account B's record",
    "expected_evidence": (
        "Account B discovers its record and Account A receives that record successfully"
    ),
    "verification_status": "unverified",
    "verifier_run_id": None,
}
PLAN = json.dumps(
    {
        "steps": [
            {"method": "GET", "path": "/records/mine", "account": "account_b"},
            {
                "method": "GET",
                "path": "/records/{record_id}",
                "account": "account_a",
            },
        ]
    }
)


def _executed_step(account: str, body: object) -> ExecutedStep:
    path = "/records/mine" if account == "account_b" else "/records/test-record"
    return ExecutedStep(
        method="GET",
        proposed_path=path,
        resolved_path=path,
        account=account,
        executed=True,
        response={"status_code": 200, "body": body},
        result="executed",
        evidence_reference="ledger://test-event",
    )


def _account_b_discovery_step() -> ExecutedStep:
    return _executed_step(
        "account_b",
        {
            "records": [
                {
                    "id": "note-account-b-001",
                    "owner_account_id": "account-b",
                }
            ]
        },
    )


def test_exact_discovered_account_b_record_returned_to_account_a_succeeds() -> None:
    account_a_step = _executed_step(
        "account_a",
        {"id": "note-account-b-001", "owner_account_id": "account-b"},
    )

    satisfied, _reason, matching_steps = deterministic_boundary_check(
        (_account_b_discovery_step(), account_a_step)
    )

    assert satisfied is True
    assert matching_steps == (2,)


def test_different_account_b_record_returned_to_account_a_fails() -> None:
    account_a_step = _executed_step(
        "account_a",
        {"id": "note-account-b-999", "owner_account_id": "account-b"},
    )

    satisfied, _reason, matching_steps = deterministic_boundary_check(
        (_account_b_discovery_step(), account_a_step)
    )

    assert satisfied is False
    assert matching_steps == ()


@pytest.mark.parametrize("owner", [None, "account-c"])
def test_matching_record_without_account_b_ownership_fails(owner: str | None) -> None:
    returned_record = {"id": "note-account-b-001"}
    if owner is not None:
        returned_record["owner_account_id"] = owner
    account_a_step = _executed_step("account_a", returned_record)

    satisfied, _reason, matching_steps = deterministic_boundary_check(
        (_account_b_discovery_step(), account_a_step)
    )

    assert satisfied is False
    assert matching_steps == ()


def test_account_a_response_before_account_b_discovery_fails() -> None:
    account_a_step = _executed_step(
        "account_a",
        {"id": "note-account-b-001", "owner_account_id": "account-b"},
    )

    satisfied, _reason, matching_steps = deterministic_boundary_check(
        (account_a_step, _account_b_discovery_step())
    )

    assert satisfied is False
    assert matching_steps == ()


class FakeClient:
    def __init__(self, role: str, trace: list[str]) -> None:
        self.role = role
        self.trace = trace
        self.messages: list[list[dict[str, str]]] = []
        self.kwargs: list[dict[str, object]] = []

    def complete(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> str:
        self.trace.append(f"plan:{self.role}")
        self.messages.append(messages)
        self.kwargs.append(kwargs)
        return PLAN


class FailingClient(FakeClient):
    def complete(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> str:
        super().complete(messages, **kwargs)
        raise RuntimeError("provider unavailable")


class MalformedClient(FakeClient):
    def complete(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> str:
        super().complete(messages, **kwargs)
        return "not valid structured JSON"


def _run(
    success_by_attempt: tuple[bool, bool],
) -> tuple[object, dict[str, object]]:
    trace: list[str] = []
    reset_count = 0
    statuses: list[tuple[str, str, str]] = []
    findings: list[tuple[str, str, str, str, str]] = []
    evidence: list[dict[str, object]] = []
    runs: list[dict[str, object]] = []
    client_a = FakeClient("verifier_a", trace)
    client_b = FakeClient("verifier_b", trace)

    def reset() -> str:
        nonlocal reset_count
        reset_count += 1
        trace.append(f"reset:{reset_count}")
        return f"reset:unique-{reset_count}:state-sha256:identical"

    def call(method: str, path: str, token: str) -> dict[str, object]:
        trace.append(f"call:{reset_count}:{method}:{path}:{token}")
        assert method == "GET"
        if path == "/records/mine":
            assert token == "token-account-b-fixed"
            return {
                "status_code": 200,
                "body": {
                    "records": [
                        {
                            "id": "note-account-b-001",
                            "owner_account_id": "account-b",
                        }
                    ]
                },
            }
        assert path == "/records/note-account-b-001"
        assert token == "token-account-a-fixed"
        if success_by_attempt[reset_count - 1]:
            return {
                "status_code": 200,
                "body": {
                    "id": "note-account-b-001",
                    "owner_account_id": "account-b",
                },
            }
        return {"status_code": 404, "body": {"detail": "Record not found"}}

    result = run_verifier(
        HYPOTHESIS_ID,
        client_a=client_a,
        client_b=client_b,
        hypothesis_reader=lambda _hypothesis_id: HYPOTHESIS,
        resetter=reset,
        endpoint_caller=call,
        evidence_recorder=lambda **kwargs: evidence.append(kwargs),
        status_updater=lambda *args: statuses.append(args),
        finding_recorder=lambda *args: findings.append(args) or "finding-123",
        run_recorder=lambda **kwargs: runs.append(kwargs),
    )
    context = {
        "trace": trace,
        "reset_count": reset_count,
        "statuses": statuses,
        "findings": findings,
        "evidence": evidence,
        "runs": runs,
        "client_a": client_a,
        "client_b": client_b,
    }
    return result, context


def test_both_attempts_succeed_verifies_and_creates_finding() -> None:
    result, context = _run((True, True))

    assert result.verdict == "verified"
    assert result.finding_id == "finding-123"
    assert [attempt.check.satisfied for attempt in result.attempts] == [True, True]
    assert context["statuses"][0][1] == "verified"
    assert len(context["findings"]) == 1
    assert "ownership check server-side" in context["findings"][0][4]
    action_types = [event["action_type"] for event in context["evidence"]]
    assert action_types.count("verifier_plan_proposed") == 2
    assert action_types.count("verifier_call_result") == 4
    assert action_types.count("verifier_deterministic_check") == 2
    assert action_types[-1] == "verifier_final_verdict"


def test_both_attempts_fail_stays_unverified_without_finding() -> None:
    result, context = _run((False, False))

    assert result.verdict == "unverified"
    assert result.finding_id is None
    assert [attempt.check.satisfied for attempt in result.attempts] == [False, False]
    assert context["statuses"][0][1] == "unverified"
    assert context["findings"] == []


def test_disagreement_is_inconclusive_without_finding() -> None:
    result, context = _run((True, False))

    assert result.verdict == "inconclusive"
    assert result.finding_id is None
    assert [attempt.check.satisfied for attempt in result.attempts] == [True, False]
    assert context["statuses"][0][1] == "inconclusive"
    assert context["findings"] == []


def test_each_attempt_resets_first_and_uses_independent_identical_state() -> None:
    result, context = _run((True, True))

    trace = context["trace"]
    assert context["reset_count"] == 2
    assert trace.index("reset:1") < trace.index("plan:verifier_a")
    assert trace.index("reset:2") < trace.index("plan:verifier_b")
    assert trace.index("plan:verifier_a") < trace.index("reset:2")
    assert any(entry.startswith("call:1:") for entry in trace)
    assert any(entry.startswith("call:2:") for entry in trace)
    assert result.attempts[0].snapshot_id != result.attempts[1].snapshot_id
    assert {
        snapshot.rsplit(":state-sha256:", 1)[1]
        for snapshot in (attempt.snapshot_id for attempt in result.attempts)
    } == {"identical"}

    client_a = context["client_a"]
    client_b = context["client_b"]
    assert client_a.messages == client_b.messages
    assert client_a.kwargs == client_b.kwargs == [
        {"response_format": {"type": "json_object"}}
    ]


@pytest.mark.parametrize("client_type", [FailingClient, MalformedClient])
def test_incomplete_second_provider_attempt_fails_closed_without_verdict_or_finding(
    client_type: type[FakeClient],
) -> None:
    trace: list[str] = []
    reset_count = 0
    statuses: list[tuple[str, str, str]] = []
    findings: list[tuple[str, str, str, str, str]] = []
    runs: list[dict[str, object]] = []

    def reset() -> str:
        nonlocal reset_count
        reset_count += 1
        trace.append(f"reset:{reset_count}")
        return f"reset:unique-{reset_count}:state-sha256:identical"

    def call(method: str, path: str, token: str) -> dict[str, object]:
        if path == "/records/mine":
            return {
                "status_code": 200,
                "body": {
                    "records": [
                        {
                            "id": "note-account-b-001",
                            "owner_account_id": "account-b",
                        }
                    ]
                },
            }
        return {
            "status_code": 200,
            "body": {
                "id": "note-account-b-001",
                "owner_account_id": "account-b",
            },
        }

    with pytest.raises((RuntimeError, ValueError)):
        run_verifier(
            HYPOTHESIS_ID,
            client_a=FakeClient("verifier_a", trace),
            client_b=client_type("verifier_b", trace),
            hypothesis_reader=lambda _hypothesis_id: HYPOTHESIS,
            resetter=reset,
            endpoint_caller=call,
            evidence_recorder=lambda **_kwargs: None,
            status_updater=lambda *args: statuses.append(args),
            finding_recorder=lambda *args: findings.append(args) or "unexpected",
            run_recorder=lambda **kwargs: runs.append(kwargs),
        )

    assert reset_count == 2
    assert statuses == []
    assert findings == []
    assert runs[-1]["status"] == "failed"
    assert "plan:verifier_a" in trace
    assert "plan:verifier_b" in trace
