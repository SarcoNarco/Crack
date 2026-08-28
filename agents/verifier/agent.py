"""Independently reproduce one school-portal hypothesis and decide its status in code."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agents.workflow.agent import WORKFLOW_APP_RULE, deterministic_workflow_check
from coordinator.progress import ProgressCallback, notify
from ledger.init_db import record_run
from model_router import ModelClient, get_client
from scope_controller import (
    call_app_endpoint,
    read_hypothesis,
    record_evidence,
    record_finding,
    reset_environment,
    update_verification_status,
)


_LEDGER_DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "ledger.db"
_ROLE_TOKENS = {
    "student_a": "token-student-a-fixed",
    "student_b": "token-student-b-fixed",
    "teacher": "token-teacher-fixed",
}
_AUTHORIZATION_APP_RULE = "GET /submissions/{submission_id}/grade must enforce student ownership"
_DECLARED_SCOPES = {
    "authorization": "two independent model-planned, clean-reset GET-only cross-student submission-detail reproductions",
    "workflow": "two independent model-planned, clean-reset Teacher grade-transition reproductions",
}
_MAX_PLAN_STEPS = 5
_DISCOVERY_PATH = "/submissions/mine"
_PLACEHOLDER_PATH = "/submissions/{submission_id}/grade"


class VerifierError(RuntimeError):
    """Raised when a verification pass cannot remain bounded and deterministic."""


class HypothesisInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    affected_app_rule: str = Field(min_length=1)
    concise_claim: str = Field(min_length=1)
    expected_evidence: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["GET"]
    path: str = Field(min_length=1, max_length=140)
    role: Literal["student_a", "student_b"]

    @field_validator("path")
    @classmethod
    def path_is_a_bounded_submission_route(cls, value: str) -> str:
        if value in {"/submissions/mine", _PLACEHOLDER_PATH}:
            return value
        if re.fullmatch(r"/submissions/[A-Za-z0-9_-]{1,100}/grade", value):
            return value
        raise ValueError("path must be /submissions/mine, a submission-grade placeholder, or one concrete submission-grade path")


class ReproductionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep] = Field(min_length=1, max_length=_MAX_PLAN_STEPS)


class WorkflowPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["list_teacher_grades", "publish_grade"]


class WorkflowReproductionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[WorkflowPlanStep] = Field(min_length=2, max_length=2)

    @field_validator("steps")
    @classmethod
    def exact_workflow_operations(cls, value: list[WorkflowPlanStep]) -> list[WorkflowPlanStep]:
        if [step.operation for step in value] != ["list_teacher_grades", "publish_grade"]:
            raise ValueError("workflow plans must list Teacher grades before publishing one grade")
        return value


@dataclass(frozen=True)
class ExecutedStep:
    method: str
    proposed_path: str
    resolved_path: str | None
    role: str
    executed: bool
    response: dict[str, object] | None
    result: str
    evidence_reference: str


@dataclass(frozen=True)
class DeterministicCheck:
    satisfied: bool
    reason: str
    matching_step_indexes: tuple[int, ...]
    evidence_reference: str


@dataclass(frozen=True)
class AttemptResult:
    verifier_role: str
    snapshot_id: str
    plan: ReproductionPlan | WorkflowReproductionPlan
    executed_steps: tuple[ExecutedStep, ...]
    check: DeterministicCheck


@dataclass(frozen=True)
class VerificationResult:
    run_id: str
    hypothesis_id: str
    attempts: tuple[AttemptResult, AttemptResult]
    verdict: Literal["verified", "unverified", "inconclusive"]
    finding_id: str | None


def _hypothesis_kind(hypothesis: HypothesisInput) -> Literal["authorization", "workflow"]:
    if hypothesis.affected_app_rule == _AUTHORIZATION_APP_RULE:
        return "authorization"
    if hypothesis.affected_app_rule == WORKFLOW_APP_RULE:
        return "workflow"
    raise VerifierError("hypothesis affected_app_rule is not one of the supported code-owned rules")


def _planner_prompt(hypothesis: HypothesisInput, kind: Literal["authorization", "workflow"]) -> str:
    if kind == "workflow":
        schema = (
            '{"steps":[{"operation":"list_teacher_grades"},'
            '{"operation":"publish_grade"}]}'
        )
        instructions = (
            "The first operation lists Teacher-owned grades. The second publishes the "
            "exact draft grade ordinary code identified. Do not provide routes, methods, "
            "roles, grade IDs, states, hosts, credentials, conclusions, prose, or extra "
            "JSON fields."
        )
    else:
        schema = (
            '{"steps":[{"method":"GET","path":"/submissions/mine",'
            '"role":"student_b"},{"method":"GET",'
            '"path":"/submissions/{submission_id}/grade","role":"student_a"}]}'
        )
        instructions = (
            "Allowed roles are student_a and student_b. Allowed paths are "
            "/submissions/mine, the submission-grade placeholder, or one concrete safe "
            "submission-grade path. The placeholder is resolved by code from an earlier "
            "Student B response. Use at most five GET steps; no login, writes, hosts, "
            "tokens, conclusions, prose, or extra JSON fields."
        )
    return (
        "You are independently planning one contained reproduction attempt. You plan "
        "calls only; you do not judge the result. "
        f"Return only JSON matching exactly {schema}. {instructions}\n\n"
        f"CONCISE CLAIM:\n{hypothesis.concise_claim}\n\n"
        f"EXPECTED EVIDENCE:\n{hypothesis.expected_evidence}"
    )


def _parse_plan(
    raw_response: str,
    kind: Literal["authorization", "workflow"],
) -> ReproductionPlan | WorkflowReproductionPlan:
    fenced = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", raw_response, re.DOTALL)
    document = fenced.group(1) if fenced else raw_response
    try:
        schema = ReproductionPlan if kind == "authorization" else WorkflowReproductionPlan
        return schema.model_validate_json(document)
    except (ValidationError, ValueError) as exc:
        raise VerifierError("model response did not match the bounded verifier plan schema") from exc


def _safe_id(value: object) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        return None
    return value


def _walk_objects(value: object):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_objects(nested)


def _student_b_submission_ids(response: dict[str, object]) -> tuple[str, ...]:
    if response.get("status_code") != 200:
        return ()
    values: list[str] = []
    for item in _walk_objects(response.get("body")):
        candidate = _safe_id(item.get("submission_id"))
        if (
            candidate
            and str(item.get("student_id", "")).replace("-", "").lower()
            == "studentb"
        ):
            values.append(candidate)
    return tuple(values)


def _is_normal_flow_student_b_discovery(
    *,
    method: str,
    role: str,
    proposed_path: str,
    resolved_path: str | None,
) -> bool:
    """Accept identifiers only from Student B's fixed normal-flow list call."""
    return (
        method == "GET"
        and role == "student_b"
        and proposed_path == _DISCOVERY_PATH
        and resolved_path == _DISCOVERY_PATH
    )


def deterministic_boundary_check(
    steps: tuple[ExecutedStep, ...],
) -> tuple[bool, str, tuple[int, ...]]:
    """Require a later Student A detail response for an exact Student B submission."""
    discovered: set[str] = set()
    matches: list[int] = []
    for index, step in enumerate(steps, start=1):
        response = step.response
        if (
            not step.executed
            or response is None
            or not isinstance(response.get("status_code"), int)
            or not 200 <= response["status_code"] < 300
        ):
            continue
        if _is_normal_flow_student_b_discovery(
            method=step.method,
            role=step.role,
            proposed_path=step.proposed_path,
            resolved_path=step.resolved_path,
        ):
            discovered.update(_student_b_submission_ids(response))
            continue
        body = response.get("body")
        if step.role == "student_a" and discovered and isinstance(body, dict):
            returned_student = str(body.get("student_id", "")).replace("-", "").lower()
            if (
                body.get("submission_id") in discovered
                and returned_student == "studentb"
                and _safe_id(body.get("grade_id"))
            ):
                matches.append(index)
    if matches:
        return (
            True,
            "Student A received the exact submission previously discovered as owned by "
            "Student B, including grade detail",
            tuple(matches),
        )
    return (
        False,
        "No later successful Student A response returned an exact previously discovered "
        "Student B-owned submission and grade detail",
        (),
    )


def _response_metadata(response: dict[str, object] | None) -> dict[str, object]:
    if response is None:
        return {"status_code": None, "body_type": None, "body_sha256": None}
    body = response.get("body")
    body_hash = hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode()
    ).hexdigest()
    result: dict[str, object] = {
        "status_code": response.get("status_code"),
        "body_type": type(body).__name__,
        "body_sha256": body_hash,
    }
    if isinstance(body, dict):
        result["body_keys"] = sorted(body)
    return result


def _plan_metadata(plan: ReproductionPlan | WorkflowReproductionPlan) -> dict[str, object]:
    steps = [step.model_dump() for step in plan.steps]
    plan_hash = hashlib.sha256(json.dumps(steps, sort_keys=True).encode()).hexdigest()
    return {
        "step_count": len(steps),
        "steps": steps,
        "plan_sha256": plan_hash,
    }


def _record_run(
    *,
    run_id: str,
    started_at: str,
    status: str,
    snapshot_ids: list[str],
    kind: str = "authorization",
) -> None:
    record_run(
        run_id=run_id,
        app_version="sprint-14-school-portal",
        environment_snapshot_id=json.dumps(snapshot_ids),
        agent_role="verifier",
        declared_scope=_DECLARED_SCOPES[kind],
        start_time=started_at,
        end_time=datetime.now(UTC).isoformat(),
        token_budget=0,
        time_budget=0,
        status=status,
        database_path=_LEDGER_DATABASE_PATH,
    )


def _run_attempt(
    *,
    verifier_role: str,
    hypothesis: HypothesisInput,
    kind: Literal["authorization", "workflow"],
    client: ModelClient,
    resetter: Callable[[], str],
    endpoint_caller: Callable[[str, str, str], dict[str, object]],
    write_evidence: Callable[[str, dict[str, object], str], str],
    progress: ProgressCallback | None,
) -> AttemptResult:
    snapshot_id = resetter()
    reset_reference = write_evidence(
        "verifier_environment_reset",
        {"verifier_role": verifier_role, "snapshot_id": snapshot_id},
        f"scope-controller://reset_environment/{snapshot_id}",
    )
    notify(
        progress,
        event_type=f"{verifier_role}.reset_completed",
        stage=verifier_role,
        state="completed",
        logical_role=verifier_role,
        headline="Fresh synthetic environment prepared",
        explanation=(
            "This independent check starts from a separate reset operation. The logical "
            "state hash identifies equivalent seeded starting data."
        ),
        metadata={
            "reset_id": snapshot_id,
            "state_hash": snapshot_id.rsplit(":state-sha256:", 1)[-1],
        },
        reference=reset_reference,
    )
    plan = _parse_plan(
        client.complete(
            [{"role": "user", "content": _planner_prompt(hypothesis, kind)}],
            response_format={"type": "json_object"},
        ),
        kind,
    )
    plan_metadata = _plan_metadata(plan)
    plan_reference = write_evidence(
        "verifier_plan_proposed",
        {
            "verifier_role": verifier_role,
            "snapshot_id": snapshot_id,
            **plan_metadata,
        },
        f"verifier://{verifier_role}/plan",
    )
    notify(
        progress,
        event_type=f"{verifier_role}.plan_validated",
        stage=verifier_role,
        state="active",
        logical_role=verifier_role,
        headline=(
            "Bounded GET-only plan validated"
            if kind == "authorization"
            else "Bounded workflow-operation plan validated"
        ),
        explanation=(
            "The model proposed a plan, and ordinary validation accepted only fixed "
            "school-portal operations."
        ),
        metadata={
            "step_count": plan_metadata["step_count"],
            "plan_sha256": plan_metadata["plan_sha256"],
        },
        reference=plan_reference,
    )

    discovered_submission_id: str | None = None
    discovered_grade_id: str | None = None
    executed_steps: list[ExecutedStep] = []
    for index, proposed in enumerate(plan.steps, start=1):
        if kind == "authorization":
            assert isinstance(proposed, PlanStep)
            method, role, proposed_path = proposed.method, proposed.role, proposed.path
            if proposed_path == _PLACEHOLDER_PATH:
                resolved_path = (
                    proposed_path.replace("{submission_id}", discovered_submission_id)
                    if discovered_submission_id
                    else None
                )
            else:
                resolved_path = proposed_path
        else:
            assert isinstance(proposed, WorkflowPlanStep)
            method, role = (
                ("GET", "teacher")
                if proposed.operation == "list_teacher_grades"
                else ("POST", "teacher")
            )
            proposed_path = (
                "/grades/mine"
                if proposed.operation == "list_teacher_grades"
                else "/grades/{grade_id}/publish"
            )
            resolved_path = (
                "/grades/mine"
                if proposed.operation == "list_teacher_grades"
                else (
                    f"/grades/{discovered_grade_id}/publish"
                    if discovered_grade_id
                    else None
                )
            )

        response = (
            endpoint_caller(method, resolved_path, _ROLE_TOKENS[role])
            if resolved_path
            else None
        )
        result = (
            "executed"
            if response is not None
            else "not executed: required exact discovered identifier was unavailable"
        )
        if (
            kind == "authorization"
            and response is not None
            and _is_normal_flow_student_b_discovery(
                method=method,
                role=role,
                proposed_path=proposed_path,
                resolved_path=resolved_path,
            )
        ):
            identifiers = _student_b_submission_ids(response)
            discovered_submission_id = identifiers[0] if identifiers else None
        if kind == "workflow" and proposed_path == "/grades/mine" and response is not None:
            body = response.get("body")
            if isinstance(body, dict) and isinstance(body.get("grades"), list):
                for grade in body["grades"]:
                    if (
                        isinstance(grade, dict)
                        and grade.get("teacher_id") == "teacher-001"
                        and grade.get("state") == "draft"
                    ):
                        discovered_grade_id = _safe_id(grade.get("grade_id"))
                        if discovered_grade_id:
                            break
        evidence_reference = write_evidence(
            "verifier_call_result",
            {
                "verifier_role": verifier_role,
                "snapshot_id": snapshot_id,
                "step_index": index,
                "method": method,
                "proposed_path": proposed_path,
                "resolved_path": resolved_path,
                "role": role,
                "executed": response is not None,
                "result": result,
                "response": _response_metadata(response),
            },
            f"scope-controller://call_app_endpoint/{verifier_role}/{index}",
        )
        response_metadata = _response_metadata(response)
        notify(
            progress,
            event_type=f"{verifier_role}.call_recorded",
            stage=verifier_role,
            state="active",
            logical_role=verifier_role,
            headline=f"Bounded call {index} recorded",
            explanation=(
                "The scope controller executed one bounded allowed call and retained "
                "only safe presentation metadata."
            ),
            metadata={
                "step_index": index,
                "role": role,
                "method": method,
                "proposed_path": proposed_path,
                "resolved_path": resolved_path,
                "executed": response is not None,
                "status_code": response_metadata["status_code"],
                "body_sha256": response_metadata["body_sha256"],
            },
            reference=evidence_reference,
        )
        executed_steps.append(
            ExecutedStep(
                method,
                proposed_path,
                resolved_path,
                role,
                response is not None,
                response,
                result,
                evidence_reference,
            )
        )
    if kind == "authorization":
        satisfied, reason, matching = deterministic_boundary_check(tuple(executed_steps))
    else:
        listed_response = executed_steps[0].response if executed_steps else None
        publish_response = (
            executed_steps[1].response if len(executed_steps) > 1 else None
        )
        satisfied, reason = deterministic_workflow_check(
            listed_response,
            publish_response,
            discovered_grade_id,
        )
        matching = (2,) if satisfied else ()
    check_reference = write_evidence(
        "verifier_deterministic_check",
        {
            "verifier_role": verifier_role,
            "snapshot_id": snapshot_id,
            "satisfied": satisfied,
            "reason": reason,
            "matching_step_indexes": list(matching),
        },
        f"verifier://{verifier_role}/deterministic-check",
    )
    notify(
        progress,
        event_type=f"{verifier_role}.check_completed",
        stage=verifier_role,
        state="completed",
        logical_role=verifier_role,
        headline=(
            "Exact-submission predicate evaluated"
            if kind == "authorization"
            else "Grade-transition predicate evaluated"
        ),
        explanation=reason,
        metadata={
            "satisfied": satisfied,
            "matching_step_indexes": list(matching),
        },
        reference=check_reference,
    )
    return AttemptResult(
        verifier_role,
        snapshot_id,
        plan,
        tuple(executed_steps),
        DeterministicCheck(satisfied, reason, matching, check_reference),
    )


def _verdict(first: AttemptResult, second: AttemptResult) -> Literal["verified", "unverified", "inconclusive"]:
    if first.check.satisfied and second.check.satisfied:
        return "verified"
    if not first.check.satisfied and not second.check.satisfied:
        return "unverified"
    return "inconclusive"


def _actual_reproduction_steps(attempts: tuple[AttemptResult, AttemptResult]) -> str:
    attempts_payload = [
        {
            "verifier_role": attempt.verifier_role,
            "snapshot_id": attempt.snapshot_id,
            "steps": [
                {
                    "method": step.method,
                    "proposed_path": step.proposed_path,
                    "resolved_path": step.resolved_path,
                    "role": step.role,
                    "executed": step.executed,
                    "status_code": (
                        step.response.get("status_code") if step.response else None
                    ),
                }
                for step in attempt.executed_steps
            ],
        }
        for attempt in attempts
    ]
    return json.dumps(attempts_payload, sort_keys=True)


def run_verifier(
    hypothesis_id: str,
    *,
    client_a: ModelClient | None = None,
    client_b: ModelClient | None = None,
    hypothesis_reader: Callable[[str], dict[str, str | None]] = read_hypothesis,
    resetter: Callable[[], str] = reset_environment,
    endpoint_caller: Callable[[str, str, str], dict[str, object]] = call_app_endpoint,
    evidence_recorder: Callable[..., None] = record_evidence,
    status_updater: Callable[[str, str, str], None] = update_verification_status,
    finding_recorder: Callable[[str, str, str, str, str], str] = record_finding,
    run_recorder: Callable[..., None] = _record_run,
    progress: ProgressCallback | None = None,
) -> VerificationResult:
    """Run two sequential isolated plans and derive the only allowed verdict in ordinary code."""
    started_at = datetime.now(UTC).isoformat()
    run_id = f"verifier:{uuid.uuid4()}"
    snapshots: list[str] = []
    sequence = 0
    references: list[str] = []

    def write_evidence(action_type: str, summary: dict[str, object], artifact_reference: str) -> str:
        nonlocal sequence
        reference = f"ledger://run/{run_id}/event/{sequence}"
        evidence_recorder(
            run_id=run_id,
            sequence_number=sequence,
            action_type=action_type,
            request_response_summary=json.dumps(summary, sort_keys=True),
            artifact_reference=artifact_reference,
            policy_decision="allowed",
        )
        references.append(reference)
        sequence += 1
        return reference

    try:
        try:
            hypothesis = HypothesisInput.model_validate(hypothesis_reader(hypothesis_id))
        except (ValidationError, ValueError) as exc:
            raise VerifierError(f"could not read hypothesis {hypothesis_id!r}") from exc
        if hypothesis.id != hypothesis_id or hypothesis.verification_status != "unverified":
            raise VerifierError("hypothesis must be the exact requested unverified revision")
        kind = _hypothesis_kind(hypothesis)
        notify(
            progress,
            event_type="verifier_a.activated",
            stage="verifier_a",
            state="active",
            logical_role="verifier_a",
            headline="Independent check 1 activated",
            explanation="Verifier A is a logical role executing first, not a parallel service.",
        )
        first = _run_attempt(
            verifier_role="verifier_a",
            hypothesis=hypothesis,
            kind=kind,
            client=client_a or get_client("verifier_a"),
            resetter=resetter,
            endpoint_caller=endpoint_caller,
            write_evidence=write_evidence,
            progress=progress,
        )
        snapshots.append(first.snapshot_id)
        notify(
            progress,
            event_type="verifier_a.completed",
            stage="verifier_a",
            state="completed",
            logical_role="verifier_a",
            headline="Independent check 1 completed",
            explanation="Verifier A finished before Verifier B was activated.",
            metadata={"satisfied": first.check.satisfied},
            reference=first.check.evidence_reference,
        )
        notify(
            progress,
            event_type="verifier_b.activated",
            stage="verifier_b",
            state="active",
            logical_role="verifier_b",
            headline="Independent check 2 activated",
            explanation=(
                "Verifier B starts from its own fresh reset after Verifier A completed."
            ),
        )
        second = _run_attempt(
            verifier_role="verifier_b",
            hypothesis=hypothesis,
            kind=kind,
            client=client_b or get_client("verifier_b"),
            resetter=resetter,
            endpoint_caller=endpoint_caller,
            write_evidence=write_evidence,
            progress=progress,
        )
        snapshots.append(second.snapshot_id)
        notify(
            progress,
            event_type="verifier_b.completed",
            stage="verifier_b",
            state="completed",
            logical_role="verifier_b",
            headline="Independent check 2 completed",
            explanation="Verifier B completed its separately reset bounded reproduction.",
            metadata={"satisfied": second.check.satisfied},
            reference=second.check.evidence_reference,
        )
        verdict = _verdict(first, second)
        notify(
            progress,
            event_type="consensus.started",
            stage="consensus",
            state="active",
            logical_role="ordinary_code",
            headline="Code-owned consensus evaluation started",
            explanation="Ordinary Python code compares the two deterministic checks.",
            metadata={
                "check_1_satisfied": first.check.satisfied,
                "check_2_satisfied": second.check.satisfied,
            },
        )
        verdict_reference = write_evidence(
            "verifier_final_verdict",
            {
                "hypothesis_id": hypothesis_id,
                "verifier_a_satisfied": first.check.satisfied,
                "verifier_b_satisfied": second.check.satisfied,
                "verdict": verdict,
            },
            f"verifier://verdict/{hypothesis_id}",
        )
        status_updater(hypothesis_id, verdict, run_id)
        notify(
            progress,
            event_type="consensus.completed",
            stage="consensus",
            state="completed",
            logical_role="ordinary_code",
            headline=f"Code-owned verdict: {verdict}",
            explanation=(
                "Two passes produce verified, two failures produce unverified, and "
                "disagreement produces inconclusive."
            ),
            metadata={
                "check_1_satisfied": first.check.satisfied,
                "check_2_satisfied": second.check.satisfied,
                "verdict": verdict,
            },
            reference=verdict_reference,
        )
        finding_id = None
        if verdict == "verified":
            remediation = (
                "Require the reviewed state before publishing grades."
                if kind == "workflow"
                else "Enforce student ownership before returning submission and grade detail."
            )
            finding_id = finding_recorder(
                hypothesis_id,
                (
                    "High impact: two independent clean-reset attempts demonstrated the "
                    "same contained school-portal defect."
                ),
                _actual_reproduction_steps((first, second)),
                json.dumps(references),
                remediation,
            )
            notify(
                progress,
                event_type="finding.recorded",
                stage="consensus",
                state="completed",
                logical_role="ordinary_code",
                headline="Verified finding recorded",
                explanation=(
                    "A finding was created only because both deterministic checks passed "
                    "and the append-only hypothesis status is verified."
                ),
                metadata={"finding_id": finding_id, "hypothesis_id": hypothesis_id},
                reference=f"ledger://finding/{finding_id}",
            )
        run_recorder(
            run_id=run_id,
            started_at=started_at,
            status="completed",
            snapshot_ids=snapshots,
            kind=kind,
        )
        return VerificationResult(run_id, hypothesis_id, (first, second), verdict, finding_id)
    except Exception:
        run_recorder(
            run_id=run_id,
            started_at=started_at,
            status="failed",
            snapshot_ids=snapshots,
            kind=locals().get("kind", "authorization"),
        )
        raise
