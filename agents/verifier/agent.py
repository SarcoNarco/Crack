"""Independently reproduce one hypothesis and decide its status in code."""

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
_ACCOUNT_TOKENS = {
    "account_a": "token-account-a-fixed",
    "account_b": "token-account-b-fixed",
}
_ACCOUNT_OWNER_NAMES = {"account_a": "accounta", "account_b": "accountb"}
_OWNER_FIELDS = frozenset(
    {"owner", "owner_id", "owner_account_id", "account", "account_id"}
)
_ID_FIELDS = frozenset({"id", "record_id"})
_STRUCTURED_OUTPUT = {"type": "json_object"}
_DECLARED_SCOPE = (
    "two independent model-planned, clean-reset GET-only authorization reproductions"
)
_MAX_PLAN_STEPS = 5
_PLACEHOLDER_PATH = "/records/{record_id}"


class VerifierError(RuntimeError):
    """Raised when a verification pass cannot remain bounded and deterministic."""


class HypothesisInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    concise_claim: str = Field(min_length=1)
    expected_evidence: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)


class PlanStep(BaseModel):
    """One bounded call proposed by a verifier model."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["GET"]
    path: str = Field(min_length=1, max_length=140)
    account: Literal["account_a", "account_b"]

    @field_validator("path")
    @classmethod
    def path_is_a_bounded_record_route(cls, value: str) -> str:
        if value in {"/records/mine", _PLACEHOLDER_PATH}:
            return value
        if re.fullmatch(r"/records/[A-Za-z0-9_-]{1,100}", value):
            return value
        raise ValueError(
            "path must be /records/mine, /records/{record_id}, or one concrete record path"
        )


class ReproductionPlan(BaseModel):
    """The only model-controlled data: a small sequence of safe read calls."""

    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep] = Field(min_length=1, max_length=_MAX_PLAN_STEPS)


@dataclass(frozen=True)
class ExecutedStep:
    method: str
    proposed_path: str
    resolved_path: str | None
    account: str
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
    plan: ReproductionPlan
    executed_steps: tuple[ExecutedStep, ...]
    check: DeterministicCheck


@dataclass(frozen=True)
class VerificationResult:
    run_id: str
    hypothesis_id: str
    attempts: tuple[AttemptResult, AttemptResult]
    verdict: Literal["verified", "unverified", "inconclusive"]
    finding_id: str | None


def _planner_prompt(hypothesis: HypothesisInput) -> str:
    return (
        "You are independently planning a reproduction attempt in a contained demo notes app. "
        "You plan calls only; you do not judge whether the attempt succeeds. Return only JSON "
        "matching exactly "
        '{"steps":[{"method":"GET","path":"/records/mine","account":"account_b"},'
        '{"method":"GET","path":"/records/{record_id}","account":"account_a"}]}. '
        "Allowed accounts are account_a and account_b. Allowed paths are /records/mine, "
        "/records/{record_id}, or a concrete /records/<safe-id> path. The {record_id} placeholder "
        "is resolved by code from an earlier Account B response. Use at most five GET steps; no "
        "login, writes, hosts, tokens, conclusions, prose, or extra JSON fields.\n\n"
        f"CONCISE CLAIM:\n{hypothesis.concise_claim}\n\n"
        f"EXPECTED EVIDENCE:\n{hypothesis.expected_evidence}"
    )


def _parse_plan(raw_response: str) -> ReproductionPlan:
    fenced = re.fullmatch(
        r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", raw_response, re.DOTALL
    )
    document = fenced.group(1) if fenced else raw_response
    try:
        return ReproductionPlan.model_validate_json(document)
    except (ValidationError, ValueError) as exc:
        raise VerifierError("model response did not match the bounded verifier plan schema") from exc


def _normalise_identity(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _walk_objects(value: object):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_objects(nested)


def _direct_field(record: dict[object, object], names: frozenset[str]) -> object | None:
    for key, value in record.items():
        if isinstance(key, str) and key.lower() in names and value is not None:
            return value
    return None


def _safe_record_id(value: object) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        return None
    return value


def _account_b_record_ids(response: dict[str, object]) -> tuple[str, ...]:
    record_ids: list[str] = []
    for record in _walk_objects(response.get("body")):
        owner = _direct_field(record, _OWNER_FIELDS)
        record_id = _safe_record_id(_direct_field(record, _ID_FIELDS))
        if _normalise_identity(owner) == _ACCOUNT_OWNER_NAMES["account_b"] and record_id:
            record_ids.append(record_id)
    return tuple(record_ids)


def _discover_account_b_record_id(response: dict[str, object]) -> str | None:
    record_ids = _account_b_record_ids(response)
    return record_ids[0] if record_ids else None


def deterministic_boundary_check(steps: tuple[ExecutedStep, ...]) -> tuple[bool, str, tuple[int, ...]]:
    """Decide success without consulting either model or its wording."""
    discovered_account_b_record_ids: set[str] = set()
    matches: list[int] = []
    for index, step in enumerate(steps, start=1):
        response = step.response
        if not step.executed or response is None:
            continue
        status_code = response.get("status_code")
        if not isinstance(status_code, int) or not 200 <= status_code < 300:
            continue

        if step.account == "account_b":
            discovered_account_b_record_ids.update(_account_b_record_ids(response))
            continue
        if step.account != "account_a" or not discovered_account_b_record_ids:
            continue

        for record in _walk_objects(response.get("body")):
            owner = _direct_field(record, _OWNER_FIELDS)
            record_id = _safe_record_id(_direct_field(record, _ID_FIELDS))
            if (
                record_id in discovered_account_b_record_ids
                and _normalise_identity(owner) == _ACCOUNT_OWNER_NAMES["account_b"]
            ):
                matches.append(index)
                break

    if matches:
        return (
            True,
            "Account A received the exact record previously discovered as owned by Account B",
            tuple(matches),
        )
    return (
        False,
        "No later successful Account A response returned an exact previously discovered Account B-owned record",
        (),
    )


def _response_metadata(response: dict[str, object] | None) -> dict[str, object]:
    if response is None:
        return {"status_code": None, "body_type": None, "body_sha256": None}
    body = response.get("body")
    encoded_body = json.dumps(body, sort_keys=True, default=str).encode()
    metadata: dict[str, object] = {
        "status_code": response.get("status_code"),
        "body_type": type(body).__name__,
        "body_sha256": hashlib.sha256(encoded_body).hexdigest(),
    }
    if isinstance(body, dict):
        metadata["body_keys"] = sorted(str(key) for key in body)
    return metadata


def _plan_metadata(plan: ReproductionPlan) -> dict[str, object]:
    steps = [step.model_dump() for step in plan.steps]
    encoded = json.dumps(steps, sort_keys=True).encode()
    return {
        "step_count": len(steps),
        "steps": steps,
        "plan_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _record_run(
    *, run_id: str, started_at: str, status: str, snapshot_ids: list[str]
) -> None:
    record_run(
        run_id=run_id,
        app_version="sprint-1-seeded-demo-app",
        environment_snapshot_id=json.dumps(snapshot_ids),
        agent_role="verifier",
        declared_scope=_DECLARED_SCOPE,
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
    client: ModelClient,
    resetter: Callable[[], str],
    endpoint_caller: Callable[[str, str, str], dict[str, object]],
    write_evidence: Callable[[str, dict[str, object], str], str],
) -> AttemptResult:
    snapshot_id = resetter()
    write_evidence(
        "verifier_environment_reset",
        {"verifier_role": verifier_role, "snapshot_id": snapshot_id},
        f"scope-controller://reset_environment/{snapshot_id}",
    )

    plan = _parse_plan(
        client.complete(
            [{"role": "user", "content": _planner_prompt(hypothesis)}],
            response_format=_STRUCTURED_OUTPUT,
        )
    )
    write_evidence(
        "verifier_plan_proposed",
        {"verifier_role": verifier_role, "snapshot_id": snapshot_id, **_plan_metadata(plan)},
        f"verifier://{verifier_role}/plan",
    )

    discovered_record_id: str | None = None
    executed_steps: list[ExecutedStep] = []
    for index, proposed in enumerate(plan.steps, start=1):
        resolved_path = proposed.path
        if proposed.path == _PLACEHOLDER_PATH:
            resolved_path = (
                proposed.path.replace("{record_id}", discovered_record_id)
                if discovered_record_id
                else None
            )

        response: dict[str, object] | None = None
        if resolved_path is None:
            result = "not executed: no Account B record ID was available for the placeholder"
        else:
            response = endpoint_caller(
                proposed.method, resolved_path, _ACCOUNT_TOKENS[proposed.account]
            )
            result = "executed"
            if proposed.account == "account_b":
                discovered_record_id = (
                    _discover_account_b_record_id(response) or discovered_record_id
                )

        evidence_reference = write_evidence(
            "verifier_call_result",
            {
                "verifier_role": verifier_role,
                "snapshot_id": snapshot_id,
                "step_index": index,
                "method": proposed.method,
                "proposed_path": proposed.path,
                "resolved_path": resolved_path,
                "account": proposed.account,
                "executed": response is not None,
                "result": result,
                "response": _response_metadata(response),
            },
            f"scope-controller://call_app_endpoint/{verifier_role}/{index}",
        )
        executed_steps.append(
            ExecutedStep(
                method=proposed.method,
                proposed_path=proposed.path,
                resolved_path=resolved_path,
                account=proposed.account,
                executed=response is not None,
                response=response,
                result=result,
                evidence_reference=evidence_reference,
            )
        )

    satisfied, reason, matching_steps = deterministic_boundary_check(tuple(executed_steps))
    check_reference = write_evidence(
        "verifier_deterministic_check",
        {
            "verifier_role": verifier_role,
            "snapshot_id": snapshot_id,
            "satisfied": satisfied,
            "reason": reason,
            "matching_step_indexes": list(matching_steps),
        },
        f"verifier://{verifier_role}/deterministic-check",
    )
    return AttemptResult(
        verifier_role=verifier_role,
        snapshot_id=snapshot_id,
        plan=plan,
        executed_steps=tuple(executed_steps),
        check=DeterministicCheck(satisfied, reason, matching_steps, check_reference),
    )


def _verdict(first: AttemptResult, second: AttemptResult) -> Literal[
    "verified", "unverified", "inconclusive"
]:
    if first.check.satisfied and second.check.satisfied:
        return "verified"
    if not first.check.satisfied and not second.check.satisfied:
        return "unverified"
    return "inconclusive"


def _actual_reproduction_steps(attempts: tuple[AttemptResult, AttemptResult]) -> str:
    payload = []
    for attempt in attempts:
        payload.append(
            {
                "verifier_role": attempt.verifier_role,
                "snapshot_id": attempt.snapshot_id,
                "steps": [
                    {
                        "method": step.method,
                        "proposed_path": step.proposed_path,
                        "resolved_path": step.resolved_path,
                        "account": step.account,
                        "executed": step.executed,
                        "status_code": (
                            step.response.get("status_code") if step.response else None
                        ),
                    }
                    for step in attempt.executed_steps
                ],
            }
        )
    return json.dumps(payload, sort_keys=True)


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
) -> VerificationResult:
    """Run two isolated plans and derive the only allowed verdict in ordinary code."""
    started_at = datetime.now(UTC).isoformat()
    run_id = f"verifier:{uuid.uuid4()}"
    snapshot_ids: list[str] = []
    sequence_number = 0
    evidence_references: list[str] = []

    def write_evidence(
        action_type: str, summary: dict[str, object], artifact_reference: str
    ) -> str:
        nonlocal sequence_number
        reference = f"ledger://run/{run_id}/event/{sequence_number}"
        evidence_recorder(
            run_id=run_id,
            sequence_number=sequence_number,
            action_type=action_type,
            request_response_summary=json.dumps(summary, sort_keys=True),
            artifact_reference=artifact_reference,
            policy_decision="allowed",
        )
        evidence_references.append(reference)
        sequence_number += 1
        return reference

    try:
        try:
            hypothesis = HypothesisInput.model_validate(hypothesis_reader(hypothesis_id))
        except (ValidationError, ValueError) as exc:
            raise VerifierError(f"could not read hypothesis {hypothesis_id!r}") from exc
        if hypothesis.id != hypothesis_id:
            raise VerifierError("scope controller returned a different hypothesis ID")
        if hypothesis.verification_status != "unverified":
            raise VerifierError(
                f"hypothesis {hypothesis_id!r} is not unverified; latest status is "
                f"{hypothesis.verification_status!r}"
            )

        first = _run_attempt(
            verifier_role="verifier_a",
            hypothesis=hypothesis,
            client=client_a or get_client("verifier_a"),
            resetter=resetter,
            endpoint_caller=endpoint_caller,
            write_evidence=write_evidence,
        )
        snapshot_ids.append(first.snapshot_id)

        second = _run_attempt(
            verifier_role="verifier_b",
            hypothesis=hypothesis,
            client=client_b or get_client("verifier_b"),
            resetter=resetter,
            endpoint_caller=endpoint_caller,
            write_evidence=write_evidence,
        )
        snapshot_ids.append(second.snapshot_id)

        attempts = (first, second)
        verdict = _verdict(first, second)
        write_evidence(
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

        finding_id: str | None = None
        if verdict == "verified":
            finding_id = finding_recorder(
                hypothesis_id,
                (
                    "High impact: two independent clean-reset attempts demonstrated that "
                    "Account A can read a record owned by another account."
                ),
                _actual_reproduction_steps(attempts),
                json.dumps(evidence_references),
                "Enforce an ownership check server-side before returning the record.",
            )

        run_recorder(
            run_id=run_id,
            started_at=started_at,
            status="completed",
            snapshot_ids=snapshot_ids,
        )
        return VerificationResult(run_id, hypothesis_id, attempts, verdict, finding_id)
    except Exception:
        run_recorder(
            run_id=run_id,
            started_at=started_at,
            status="failed",
            snapshot_ids=snapshot_ids,
        )
        raise
