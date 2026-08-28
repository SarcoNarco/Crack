"""Run one bounded, contract-driven cross-student authorization check."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from coordinator.progress import ProgressCallback, notify
from ledger.init_db import record_run
from model_router import ModelClient, get_client
from scope_controller import call_app_endpoint, record_evidence, submit_hypothesis


_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "mapper" / "output" / "app_contract.json"
_LEDGER_DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "ledger.db"
_MAX_ENDPOINT_CALLS = 2
_STUDENT_A_TOKEN = "token-student-a-fixed"
_STUDENT_B_TOKEN = "token-student-b-fixed"
_DECLARED_SCOPE = "bounded contract-derived Student A to Student B submission-detail authorization checks"
_STRUCTURED_OUTPUT = {"type": "json_object"}
_AUTHORIZATION_APP_RULE = "GET /submissions/{submission_id}/grade must enforce student ownership"


class ContractRoute(BaseModel):
    method: str = Field(min_length=1)
    path: str = Field(min_length=1)
    description: str = Field(min_length=1)


class AppContract(BaseModel):
    routes: list[ContractRoute]
    roles: list[str]
    assumptions: list[str]


class IdentityPlan(BaseModel):
    """The model may select only a declared submission-detail route."""

    model_config = ConfigDict(extra="forbid")

    boundary_route: str = Field(min_length=1)


class HypothesisWording(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concise_claim: str = Field(min_length=1, max_length=500)
    expected_evidence: str = Field(min_length=1, max_length=1000)


class IdentityError(RuntimeError):
    """Raised when the bounded identity pass cannot safely interpret model output."""


@dataclass(frozen=True)
class TestResult:
    method: str
    path: str | None
    as_role: str
    purpose: str
    status_code: int | None
    result: str


@dataclass(frozen=True)
class IdentityRunResult:
    run_id: str
    tests: list[TestResult]
    hypothesis_ids: list[str]
    hypothesis_claims: list[str]
    plan_was_capped: bool


def _normalise_identity(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _submission_routes(contract: AppContract) -> list[ContractRoute]:
    return [
        route
        for route in contract.routes
        if route.method.upper() == "GET"
        and route.path == "/submissions/{submission_id}/grade"
    ]


def _my_submissions_route(contract: AppContract) -> ContractRoute | None:
    return next(
        (
            route
            for route in contract.routes
            if route.method.upper() == "GET" and route.path == "/submissions/mine"
        ),
        None,
    )


def _planner_prompt(contract: AppContract) -> str:
    routes = [route.model_dump() for route in _submission_routes(contract)]
    return (
        "You are selecting the submission-detail route for a contained authorization test. Work only "
        "from this app contract. Return only JSON matching exactly "
        '{"boundary_route":"/submissions/{submission_id}/grade"}. Select the listed GET route; '
        "do not select IDs, roles, calls, writes, login, or routes outside the following choices: "
        f"{json.dumps(routes)}.\n\nAPP CONTRACT:\n{contract.model_dump_json(indent=2)}"
    )


def _hypothesis_prompt(*, method: str, route: str, submission_id: str) -> str:
    return (
        "You are wording an unverified authorization hypothesis for a contained synthetic school portal. "
        "Ordinary code observed Student A receive a successful response for a submission which "
        f"Student B had just observed as their own, via {method} {route.replace('{submission_id}', submission_id)}. "
        "Return only JSON exactly shaped as "
        '{"concise_claim":"...","expected_evidence":"..."}. '
        "State the route and missing student ownership boundary precisely. Do not call it verified and "
        "do not add severity or remediation claims."
    )


def _parse_model_json(raw_response: str, schema: type[BaseModel]) -> BaseModel:
    thinking_prefix = re.fullmatch(
        r"\s*<think>.*?</think>\s*(?P<response>.*)", raw_response, re.DOTALL
    )
    response = thinking_prefix.group("response") if thinking_prefix else raw_response
    fenced = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", response, re.DOTALL)
    document = fenced.group(1) if fenced else response
    try:
        return schema.model_validate_json(document)
    except (ValidationError, ValueError) as exc:
        raise IdentityError("LLM response did not match the bounded identity-agent schema") from exc


def _load_contract(contract_path: Path) -> AppContract:
    try:
        return AppContract.model_validate_json(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise IdentityError(f"Could not load mapper app contract at {contract_path}") from exc


def _contract_route_for(planned_path: str, contract: AppContract) -> ContractRoute | None:
    return next(
        (
            route
            for route in _submission_routes(contract)
            if planned_path == route.path
        ),
        None,
    )


def _safe_submission_id(value: object) -> str | None:
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


def _student_b_submission_id(response: dict[str, object]) -> str | None:
    if response.get("status_code") != 200:
        return None
    for item in _walk_objects(response.get("body")):
        submission_id = _safe_submission_id(item.get("submission_id"))
        if submission_id and _normalise_identity(item.get("student_id")) == "studentb":
            return submission_id
    return None


def _cross_student_success(response: dict[str, object], submission_id: str) -> bool:
    body = response.get("body")
    return (
        isinstance(response.get("status_code"), int)
        and 200 <= response["status_code"] < 300
        and isinstance(body, dict)
        and body.get("submission_id") == submission_id
        and _normalise_identity(body.get("student_id")) == "studentb"
        and _safe_submission_id(body.get("grade_id")) is not None
    )


def _response_summary(response: dict[str, object], result: str) -> str:
    return json.dumps({"result": result, "status_code": response.get("status_code")}, sort_keys=True)


def _record_run(*, run_id: str, started_at: str, status: str, app_version: str) -> None:
    record_run(
        run_id=run_id,
        app_version=app_version,
        environment_snapshot_id="live-app-through-scope-controller",
        agent_role="identity",
        declared_scope=_DECLARED_SCOPE,
        start_time=started_at,
        end_time=datetime.now(UTC).isoformat(),
        token_budget=0,
        time_budget=0,
        status=status,
        database_path=_LEDGER_DATABASE_PATH,
    )


def run_identity(
    *,
    client: ModelClient | None = None,
    contract_path: Path = _CONTRACT_PATH,
    endpoint_caller: Callable[[str, str, str], dict[str, object]] = call_app_endpoint,
    evidence_recorder: Callable[..., None] = record_evidence,
    hypothesis_submitter: Callable[[str, str, str, str], str] = submit_hypothesis,
    run_recorder: Callable[..., None] = _record_run,
    progress: ProgressCallback | None = None,
) -> IdentityRunResult:
    """Execute exactly two normal-flow GET calls when Student B discovery succeeds."""
    started_at = datetime.now(UTC).isoformat()
    run_id = f"identity:{uuid.uuid4()}"
    contract = _load_contract(contract_path)
    contract_hash = hashlib.sha256(contract.model_dump_json().encode()).hexdigest()[:16]
    app_version = f"school-portal-contract-sha256:{contract_hash}"
    model_client = client or get_client("identity")
    tests: list[TestResult] = []
    hypothesis_ids: list[str] = []
    hypothesis_claims: list[str] = []
    try:
        plan = _parse_model_json(
            model_client.complete(
                [{"role": "user", "content": _planner_prompt(contract)}],
                response_format=_STRUCTURED_OUTPUT,
            ),
            IdentityPlan,
        )
        assert isinstance(plan, IdentityPlan)
        discovery_route = _my_submissions_route(contract)
        boundary_route = _contract_route_for(plan.boundary_route, contract)
        if discovery_route is None or boundary_route is None:
            raise IdentityError(
                "App contract must declare Student B discovery and a submission-grade detail route"
            )

        discovery = endpoint_caller("GET", discovery_route.path, _STUDENT_B_TOKEN)
        submission_id = _student_b_submission_id(discovery)
        discovery_result = (
            "observed Student B-owned submission"
            if submission_id
            else "did not observe a Student B-owned submission"
        )
        discovery_status = discovery.get("status_code")
        tests.append(
            TestResult(
                "GET",
                discovery_route.path,
                "student_b",
                "observe_student_b_submission",
                discovery_status if isinstance(discovery_status, int) else None,
                discovery_result,
            )
        )
        evidence_recorder(
            run_id=run_id,
            sequence_number=1,
            action_type="identity_test_result",
            request_response_summary=_response_summary(discovery, discovery_result),
            artifact_reference=(
                f"scope-controller://call_app_endpoint/GET{discovery_route.path}"
            ),
            policy_decision="allowed",
        )
        notify(
            progress,
            event_type="identity.student_b_discovery",
            stage="authorization",
            state="completed",
            logical_role="identity",
            headline="Student B submission discovery completed",
            explanation=(
                "The authorization tester used Student B's fixed identity to list only "
                "that student's submissions."
            ),
            metadata={
                "status_code": discovery_status,
                "submission_id": submission_id,
                "student": "student_b" if submission_id else None,
            },
            reference=f"scope-controller://call_app_endpoint/GET{discovery_route.path}",
        )

        if submission_id is not None:
            detail_path = boundary_route.path.replace("{submission_id}", submission_id)
            detail = endpoint_caller("GET", detail_path, _STUDENT_A_TOKEN)
            violated = _cross_student_success(detail, submission_id)
            detail_result = (
                "boundary violation: Student A received Student B submission grade detail"
                if violated
                else "no cross-student boundary violation observed"
            )
            detail_status = detail.get("status_code")
            tests.append(
                TestResult(
                    "GET",
                    detail_path,
                    "student_a",
                    "cross_student_submission_detail",
                    detail_status if isinstance(detail_status, int) else None,
                    detail_result,
                )
            )
            evidence_recorder(
                run_id=run_id,
                sequence_number=2,
                action_type="identity_test_result",
                request_response_summary=_response_summary(detail, detail_result),
                artifact_reference=f"scope-controller://call_app_endpoint/GET{detail_path}",
                policy_decision="allowed",
            )
            body = detail.get("body") if isinstance(detail.get("body"), dict) else {}
            notify(
                progress,
                event_type="identity.student_a_retrieval",
                stage="authorization",
                state="completed",
                logical_role="identity",
                headline="Student A cross-student detail retrieval completed",
                explanation=(
                    "The tester requested Student B's exact discovered submission through "
                    "Student A's fixed identity and recorded only safe metadata."
                ),
                metadata={
                    "status_code": detail_status,
                    "requested_submission_id": submission_id,
                    "returned_submission_id": body.get("submission_id"),
                    "returned_student": (
                        "student_b"
                        if _normalise_identity(body.get("student_id")) == "studentb"
                        else "other"
                    ),
                    "exact_submission_match": violated,
                },
                reference=f"scope-controller://call_app_endpoint/GET{detail_path}",
            )
            if violated:
                wording = _parse_model_json(
                    model_client.complete(
                        [
                            {
                                "role": "user",
                                "content": _hypothesis_prompt(
                                    method="GET",
                                    route=boundary_route.path,
                                    submission_id=submission_id,
                                ),
                            }
                        ],
                        response_format=_STRUCTURED_OUTPUT,
                    ),
                    HypothesisWording,
                )
                assert isinstance(wording, HypothesisWording)
                hypothesis_id = hypothesis_submitter(
                    run_id,
                    _AUTHORIZATION_APP_RULE,
                    wording.concise_claim,
                    wording.expected_evidence,
                )
                hypothesis_ids.append(hypothesis_id)
                hypothesis_claims.append(wording.concise_claim)
                notify(
                    progress,
                    event_type="hypothesis.created",
                    stage="authorization",
                    state="completed",
                    logical_role="identity",
                    headline="Unverified authorization hypothesis created",
                    explanation=(
                        "The hypothesis was recorded only after Student A received the "
                        "exact Student B-owned submission detail."
                    ),
                    metadata={"hypothesis_id": hypothesis_id},
                    reference=f"ledger://hypothesis/{hypothesis_id}",
                )
        if len(tests) > _MAX_ENDPOINT_CALLS:
            raise IdentityError("Identity endpoint-call cap exceeded")
        run_recorder(run_id=run_id, started_at=started_at, status="completed", app_version=app_version)
        return IdentityRunResult(
            run_id,
            tests,
            hypothesis_ids,
            hypothesis_claims,
            False,
        )
    except Exception:
        run_recorder(run_id=run_id, started_at=started_at, status="failed", app_version=app_version)
        raise
