"""Run one bounded, contract-derived grade-workflow business-rule check."""

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

from coordinator.progress import ProgressCallback, notify
from ledger.init_db import record_run
from model_router import ModelClient, get_client
from scope_controller import call_app_endpoint, record_evidence, submit_hypothesis


_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "mapper" / "output" / "app_contract.json"
_LEDGER_DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "ledger.db"
_MAX_ENDPOINT_CALLS = 2
_TEACHER_TOKEN = "token-teacher-fixed"
_STRUCTURED_OUTPUT = {"type": "json_object"}
WORKFLOW_RULE_ID = "review_before_publish"
WORKFLOW_APP_RULE = "WORKFLOW: a teacher must review a grade before publishing it"
_RULE_SPEC = {
    "rule_id": WORKFLOW_RULE_ID,
    "account": "teacher",
    "states": ("draft", "reviewed", "published"),
    "list_route": "/grades/mine",
    "review_route": "/grades/{grade_id}/review",
    "publish_route": "/grades/{grade_id}/publish",
    "required_predecessor": "reviewed",
    "invalid_predecessor": "draft",
}
_DECLARED_SCOPE = "bounded contract-derived Teacher grade transition checks"


class WorkflowError(RuntimeError):
    """Raised when a workflow pass cannot remain bounded and deterministic."""


class ContractRoute(BaseModel):
    method: str = Field(min_length=1)
    path: str = Field(min_length=1)
    description: str = Field(min_length=1)


class WorkflowRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: Literal["review_before_publish"]
    account: Literal["teacher"]
    states: tuple[
        Literal["draft", "reviewed", "published"],
        Literal["draft", "reviewed", "published"],
        Literal["draft", "reviewed", "published"],
    ]
    list_route: Literal["/grades/mine"]
    review_route: Literal["/grades/{grade_id}/review"]
    publish_route: Literal["/grades/{grade_id}/publish"]
    required_predecessor: Literal["reviewed"]
    invalid_predecessor: Literal["draft"]

    @field_validator("states")
    @classmethod
    def states_are_fixed(cls, value: tuple[str, str, str]) -> tuple[str, str, str]:
        if value != _RULE_SPEC["states"]:
            raise ValueError("workflow states must be draft, reviewed, published in order")
        return value


class AppContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routes: list[ContractRoute]
    roles: list[str]
    assumptions: list[str]
    workflow_rules: list[WorkflowRule] = Field(default_factory=list)


class WorkflowPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_rule_id: Literal["review_before_publish"]


class HypothesisWording(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concise_claim: str = Field(min_length=1, max_length=500)
    expected_evidence: str = Field(min_length=1, max_length=1000)


@dataclass(frozen=True)
class TestResult:
    method: str
    path: str | None
    as_role: str
    purpose: str
    status_code: int | None
    result: str


@dataclass(frozen=True)
class WorkflowRunResult:
    run_id: str
    tests: list[TestResult]
    hypothesis_ids: list[str]
    hypothesis_claims: list[str]
    plan_was_capped: bool


def _parse_model_json(raw_response: str, schema: type[BaseModel]) -> BaseModel:
    fenced = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", raw_response, re.DOTALL)
    document = fenced.group(1) if fenced else raw_response
    try:
        return schema.model_validate_json(document)
    except (ValidationError, ValueError) as exc:
        raise WorkflowError("LLM response did not match the bounded workflow-agent schema") from exc


def _load_contract(contract_path: Path) -> AppContract:
    try:
        return AppContract.model_validate_json(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise WorkflowError(f"Could not load mapper app contract at {contract_path}") from exc


def _declared_rule(contract: AppContract) -> WorkflowRule:
    if len(contract.workflow_rules) != 1:
        raise WorkflowError("App contract must declare exactly one bounded workflow rule")
    rule = contract.workflow_rules[0]
    if rule.model_dump() != _RULE_SPEC:
        raise WorkflowError("App contract workflow rule differs from the fixed supported rule")
    routes = {(route.method.upper(), route.path) for route in contract.routes}
    expected_routes = {
        ("GET", rule.list_route),
        ("POST", rule.review_route),
        ("POST", rule.publish_route),
    }
    if not expected_routes.issubset(routes):
        raise WorkflowError("App contract does not declare every required workflow operation")
    return rule


def _planner_prompt(rule: WorkflowRule) -> str:
    return (
        "You are selecting one bounded business-rule check in a contained synthetic school portal. "
        "Return only JSON exactly shaped as "
        '{"workflow_rule_id":"review_before_publish"}. '
        "The only available rule requires Teacher review before publishing a grade. Do not choose "
        "routes, methods, roles, grade IDs, states, credentials, hosts, calls, findings, or extra JSON fields.\n\n"
        f"DECLARED WORKFLOW RULE:\n{rule.model_dump_json(indent=2)}"
    )


def _hypothesis_prompt(grade_id: str) -> str:
    return (
        "You are wording an unverified workflow hypothesis for a contained synthetic school portal. "
        "Ordinary code observed the Teacher list a draft grade and then receive a successful "
        f"publish transition for that same grade ({grade_id}) without a reviewed predecessor. "
        "Return only JSON shaped exactly as "
        '{"concise_claim":"...","expected_evidence":"..."}. '
        "Do not claim verification, severity, remediation, consensus, or a finding."
    )


def _find_draft_grade(response: dict[str, object]) -> str | None:
    if response.get("status_code") != 200:
        return None
    body = response.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("grades"), list):
        return None
    for grade in body["grades"]:
        if (
            isinstance(grade, dict)
            and isinstance(grade.get("grade_id"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", grade["grade_id"])
            and grade.get("teacher_id") == "teacher-001"
            and grade.get("state") == "draft"
        ):
            return grade["grade_id"]
    return None


def deterministic_workflow_check(
    listed_response: dict[str, object] | None,
    publish_response: dict[str, object] | None,
    grade_id: str | None,
) -> tuple[bool, str]:
    """Decide the draft-to-published grade defect without model input."""
    if grade_id is None or listed_response is None or publish_response is None:
        return False, "No Teacher-owned draft grade was safely identified and published"
    if _find_draft_grade(listed_response) != grade_id:
        return False, "The listed grade was not a Teacher-owned draft grade"
    body = publish_response.get("body")
    if not isinstance(body, dict):
        return False, "The publish response did not have the required object shape"
    status_code = publish_response.get("status_code")
    if not isinstance(status_code, int) or not 200 <= status_code < 300:
        return False, "Publishing the draft grade was rejected"
    if (
        body.get("grade_id") == grade_id
        and body.get("previous_state") == "draft"
        and body.get("state") == "published"
    ):
        return True, "A draft Teacher-owned grade was published without the required reviewed state"
    return False, "The publish response did not prove a draft-to-published grade transition"


def _response_summary(response: dict[str, object], result: str) -> str:
    body = response.get("body")
    body_hash = hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode()
    ).hexdigest()
    return json.dumps(
        {
            "result": result,
            "status_code": response.get("status_code"),
            "body_sha256": body_hash,
        },
        sort_keys=True,
    )


def _record_run(*, run_id: str, started_at: str, status: str, app_version: str) -> None:
    record_run(
        run_id=run_id,
        app_version=app_version,
        environment_snapshot_id="live-app-through-scope-controller",
        agent_role="workflow",
        declared_scope=_DECLARED_SCOPE,
        start_time=started_at,
        end_time=datetime.now(UTC).isoformat(),
        token_budget=0,
        time_budget=0,
        status=status,
        database_path=_LEDGER_DATABASE_PATH,
    )


def run_workflow(
    *,
    client: ModelClient | None = None,
    contract_path: Path = _CONTRACT_PATH,
    endpoint_caller: Callable[[str, str, str], dict[str, object]] = call_app_endpoint,
    evidence_recorder: Callable[..., None] = record_evidence,
    hypothesis_submitter: Callable[[str, str, str, str], str] = submit_hypothesis,
    run_recorder: Callable[..., None] = _record_run,
    progress: ProgressCallback | None = None,
) -> WorkflowRunResult:
    """Run one fixed two-call draft-grade publish check through the scope controller."""
    started_at = datetime.now(UTC).isoformat()
    run_id = f"workflow:{uuid.uuid4()}"
    contract = _load_contract(contract_path)
    contract_hash = hashlib.sha256(contract.model_dump_json().encode()).hexdigest()[:16]
    app_version = f"school-portal-contract-sha256:{contract_hash}"
    model_client = client or get_client("workflow")
    tests: list[TestResult] = []
    hypothesis_ids: list[str] = []
    hypothesis_claims: list[str] = []
    try:
        rule = _declared_rule(contract)
        plan = _parse_model_json(
            model_client.complete(
                [{"role": "user", "content": _planner_prompt(rule)}],
                response_format=_STRUCTURED_OUTPUT,
            ),
            WorkflowPlan,
        )
        assert isinstance(plan, WorkflowPlan)
        if plan.workflow_rule_id != rule.rule_id:
            raise WorkflowError("Workflow plan selected an undeclared rule")
        listed = endpoint_caller("GET", rule.list_route, _TEACHER_TOKEN)
        grade_id = _find_draft_grade(listed)
        list_result = (
            "observed Teacher-owned draft grade"
            if grade_id
            else "did not observe Teacher-owned draft grade"
        )
        list_status = listed.get("status_code")
        tests.append(
            TestResult(
                "GET",
                rule.list_route,
                "teacher",
                "observe_owned_draft_grade",
                list_status if isinstance(list_status, int) else None,
                list_result,
            )
        )
        evidence_recorder(
            run_id=run_id,
            sequence_number=1,
            action_type="workflow_test_result",
            request_response_summary=_response_summary(listed, list_result),
            artifact_reference=f"scope-controller://call_app_endpoint/GET{rule.list_route}",
            policy_decision="allowed",
        )
        notify(
            progress,
            event_type="workflow.draft_grade_discovery",
            stage="workflow",
            state="completed",
            logical_role="workflow",
            headline="Teacher grade discovery completed",
            explanation="Bounded code identified only a Teacher-owned draft grade.",
            metadata={"status_code": list_status, "grade_id": grade_id},
            reference=f"scope-controller://call_app_endpoint/GET{rule.list_route}",
        )
        if grade_id is not None:
            publish_path = rule.publish_route.replace("{grade_id}", grade_id)
            published = endpoint_caller("POST", publish_path, _TEACHER_TOKEN)
            satisfied, result = deterministic_workflow_check(listed, published, grade_id)
            publish_status = published.get("status_code")
            tests.append(
                TestResult(
                    "POST",
                    publish_path,
                    "teacher",
                    "attempt_publish_without_review",
                    publish_status if isinstance(publish_status, int) else None,
                    result,
                )
            )
            evidence_recorder(
                run_id=run_id,
                sequence_number=2,
                action_type="workflow_test_result",
                request_response_summary=_response_summary(published, result),
                artifact_reference=(
                    f"scope-controller://call_app_endpoint/POST{publish_path}"
                ),
                policy_decision="allowed",
            )
            notify(
                progress,
                event_type="workflow.invalid_transition_checked",
                stage="workflow",
                state="completed",
                logical_role="workflow",
                headline="Draft grade publish transition checked",
                explanation=(
                    "Ordinary code evaluated the recorded response against the declared "
                    "reviewed predecessor rule."
                ),
                metadata={
                    "status_code": publish_status,
                    "grade_id": grade_id,
                    "satisfied": satisfied,
                },
                reference=f"scope-controller://call_app_endpoint/POST{publish_path}",
            )
            if satisfied:
                wording = _parse_model_json(
                    model_client.complete(
                        [{"role": "user", "content": _hypothesis_prompt(grade_id)}],
                        response_format=_STRUCTURED_OUTPUT,
                    ),
                    HypothesisWording,
                )
                assert isinstance(wording, HypothesisWording)
                hypothesis_id = hypothesis_submitter(
                    run_id,
                    WORKFLOW_APP_RULE,
                    wording.concise_claim,
                    wording.expected_evidence,
                )
                hypothesis_ids.append(hypothesis_id)
                hypothesis_claims.append(wording.concise_claim)
                notify(
                    progress,
                    event_type="hypothesis.created",
                    stage="workflow",
                    state="completed",
                    logical_role="workflow",
                    headline="Unverified workflow hypothesis created",
                    explanation=(
                        "The hypothesis was recorded only after code observed "
                        "draft-to-published grade success."
                    ),
                    metadata={"hypothesis_id": hypothesis_id},
                    reference=f"ledger://hypothesis/{hypothesis_id}",
                )
        if len(tests) > _MAX_ENDPOINT_CALLS:
            raise WorkflowError("Workflow endpoint-call cap exceeded")
        run_recorder(run_id=run_id, started_at=started_at, status="completed", app_version=app_version)
        return WorkflowRunResult(
            run_id,
            tests,
            hypothesis_ids,
            hypothesis_claims,
            False,
        )
    except Exception:
        run_recorder(run_id=run_id, started_at=started_at, status="failed", app_version=app_version)
        raise
