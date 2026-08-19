"""Run one bounded, contract-derived workflow business-rule check."""

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
_MAX_ENDPOINT_CALLS = 5
_ACCOUNT_A_TOKEN = "token-account-a-fixed"
_STRUCTURED_OUTPUT = {"type": "json_object"}
WORKFLOW_RULE_ID = "approval_before_publish"
WORKFLOW_APP_RULE = "WORKFLOW: approval is required before publishing a work item"
_RULE_SPEC = {
    "rule_id": WORKFLOW_RULE_ID,
    "account": "account_a",
    "states": ("draft", "approved", "published"),
    "list_route": "/work-items/mine",
    "approve_route": "/work-items/{work_item_id}/approve",
    "publish_route": "/work-items/{work_item_id}/publish",
    "required_predecessor": "approved",
    "invalid_predecessor": "draft",
}
_DECLARED_SCOPE = "bounded contract-derived Account A workflow transition checks"


class WorkflowError(RuntimeError):
    """Raised when a workflow pass cannot remain bounded and deterministic."""


class ContractRoute(BaseModel):
    method: str = Field(min_length=1)
    path: str = Field(min_length=1)
    description: str = Field(min_length=1)


class WorkflowRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: Literal["approval_before_publish"]
    account: Literal["account_a"]
    states: tuple[
        Literal["draft", "approved", "published"],
        Literal["draft", "approved", "published"],
        Literal["draft", "approved", "published"],
    ]
    list_route: Literal["/work-items/mine"]
    approve_route: Literal["/work-items/{work_item_id}/approve"]
    publish_route: Literal["/work-items/{work_item_id}/publish"]
    required_predecessor: Literal["approved"]
    invalid_predecessor: Literal["draft"]

    @field_validator("states")
    @classmethod
    def states_are_fixed(cls, value: tuple[str, str, str]) -> tuple[str, str, str]:
        if value != _RULE_SPEC["states"]:
            raise ValueError("workflow states must be draft, approved, published in order")
        return value


class AppContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routes: list[ContractRoute]
    roles: list[str]
    assumptions: list[str]
    workflow_rules: list[WorkflowRule] = Field(default_factory=list)


class WorkflowPlan(BaseModel):
    """The model can select only the one contract-declared workflow rule."""

    model_config = ConfigDict(extra="forbid")

    workflow_rule_id: Literal["approval_before_publish"]


class HypothesisWording(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concise_claim: str = Field(min_length=1, max_length=500)
    expected_evidence: str = Field(min_length=1, max_length=1000)


@dataclass(frozen=True)
class TestResult:
    method: str
    path: str | None
    as_account: str
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
        ("POST", rule.approve_route),
        ("POST", rule.publish_route),
    }
    if not expected_routes.issubset(routes):
        raise WorkflowError("App contract does not declare every required workflow operation")
    return rule


def _planner_prompt(rule: WorkflowRule) -> str:
    return (
        "You are selecting one bounded business-rule check in a contained synthetic app. "
        "Return only JSON exactly shaped as "
        '{"workflow_rule_id":"approval_before_publish"}. '
        "The only available rule requires approval before publish for Account A. Do not choose "
        "routes, methods, accounts, work-item IDs, states, credentials, hosts, calls, findings, "
        "or any extra JSON fields.\n\nDECLARED WORKFLOW RULE:\n"
        f"{rule.model_dump_json(indent=2)}"
    )


def _hypothesis_prompt(work_item_id: str) -> str:
    return (
        "You are wording an unverified workflow hypothesis for a contained synthetic app. "
        "Ordinary code observed Account A list a draft work item and then receive a successful "
        f"publish transition for that same item ({work_item_id}) without an approved predecessor. "
        "Return only JSON shaped exactly as "
        '{"concise_claim":"...","expected_evidence":"..."}. '
        "Do not claim verification, severity, remediation, consensus, or a finding."
    )


def _find_draft_work_item(response: dict[str, object]) -> str | None:
    if response.get("status_code") != 200:
        return None
    body = response.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("work_items"), list):
        return None
    for item in body["work_items"]:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if (
            isinstance(item_id, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", item_id)
            and item.get("owner_account_id") == "account-a"
            and item.get("state") == "draft"
        ):
            return item_id
    return None


def deterministic_workflow_check(
    listed_response: dict[str, object] | None,
    publish_response: dict[str, object] | None,
    work_item_id: str | None,
) -> tuple[bool, str]:
    """Decide the draft-to-published rule violation without model input."""
    if work_item_id is None or listed_response is None or publish_response is None:
        return False, "No owned draft work item was safely identified and published"
    if _find_draft_work_item(listed_response) != work_item_id:
        return False, "The listed item was not an Account A-owned draft work item"
    body = publish_response.get("body")
    if not isinstance(body, dict):
        return False, "The publish response did not have the required object shape"
    success = publish_response.get("status_code")
    if not isinstance(success, int) or not 200 <= success < 300:
        return False, "Publishing the draft work item was rejected"
    if (
        body.get("id") == work_item_id
        and body.get("previous_state") == "draft"
        and body.get("state") == "published"
    ):
        return True, "A draft Account A work item was published without the required approved state"
    return False, "The publish response did not prove a draft-to-published transition"


def _response_summary(response: dict[str, object] | None, result: str) -> str:
    if response is None:
        return json.dumps({"result": result}, sort_keys=True)
    body = response.get("body")
    metadata: dict[str, object] = {
        "result": result,
        "status_code": response.get("status_code"),
        "body_type": type(body).__name__,
        "body_sha256": hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest(),
    }
    if isinstance(body, dict):
        metadata["body_keys"] = sorted(body)
    return json.dumps(metadata, sort_keys=True)


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
    """Run one fixed two-call invalid transition test through the scope controller."""
    started_at = datetime.now(UTC).isoformat()
    run_id = f"workflow:{uuid.uuid4()}"
    contract = _load_contract(contract_path)
    app_version = f"contract-sha256:{hashlib.sha256(contract.model_dump_json().encode()).hexdigest()[:16]}"
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

        listed = endpoint_caller("GET", rule.list_route, _ACCOUNT_A_TOKEN)
        work_item_id = _find_draft_work_item(listed)
        list_status = listed.get("status_code")
        list_result = "observed owned draft work item" if work_item_id else "did not observe owned draft work item"
        tests.append(TestResult("GET", rule.list_route, "account_a", "observe_owned_draft", list_status if isinstance(list_status, int) else None, list_result))
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
            event_type="workflow.draft_discovery",
            stage="workflow",
            state="completed",
            logical_role="workflow",
            headline="Account A work-item discovery completed",
            explanation="Bounded code identified only an Account A-owned draft work item.",
            metadata={"status_code": list_status if isinstance(list_status, int) else None, "work_item_id": work_item_id},
            reference=f"scope-controller://call_app_endpoint/GET{rule.list_route}",
        )

        publish_response: dict[str, object] | None = None
        if work_item_id is not None:
            publish_path = rule.publish_route.replace("{work_item_id}", work_item_id)
            publish_response = endpoint_caller("POST", publish_path, _ACCOUNT_A_TOKEN)
            satisfied, result = deterministic_workflow_check(listed, publish_response, work_item_id)
            publish_status = publish_response.get("status_code")
            tests.append(TestResult("POST", publish_path, "account_a", "attempt_publish_without_approval", publish_status if isinstance(publish_status, int) else None, result))
            evidence_recorder(
                run_id=run_id,
                sequence_number=2,
                action_type="workflow_test_result",
                request_response_summary=_response_summary(publish_response, result),
                artifact_reference=f"scope-controller://call_app_endpoint/POST{publish_path}",
                policy_decision="allowed",
            )
            notify(
                progress,
                event_type="workflow.invalid_transition_checked",
                stage="workflow",
                state="completed",
                logical_role="workflow",
                headline="Draft publish transition checked",
                explanation="Ordinary code evaluated the recorded response against the declared predecessor rule.",
                metadata={"status_code": publish_status if isinstance(publish_status, int) else None, "work_item_id": work_item_id, "satisfied": satisfied},
                reference=f"scope-controller://call_app_endpoint/POST{publish_path}",
            )
            if satisfied:
                wording = _parse_model_json(
                    model_client.complete(
                        [{"role": "user", "content": _hypothesis_prompt(work_item_id)}],
                        response_format=_STRUCTURED_OUTPUT,
                    ),
                    HypothesisWording,
                )
                assert isinstance(wording, HypothesisWording)
                hypothesis_id = hypothesis_submitter(
                    run_id, WORKFLOW_APP_RULE, wording.concise_claim, wording.expected_evidence
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
                    explanation="The hypothesis was recorded only after code observed draft-to-published success.",
                    metadata={"hypothesis_id": hypothesis_id},
                    reference=f"ledger://hypothesis/{hypothesis_id}",
                )

        if len(tests) > _MAX_ENDPOINT_CALLS:
            raise WorkflowError("Workflow endpoint-call cap exceeded")
        run_recorder(run_id=run_id, started_at=started_at, status="completed", app_version=app_version)
        return WorkflowRunResult(run_id, tests, hypothesis_ids, hypothesis_claims, False)
    except Exception:
        run_recorder(run_id=run_id, started_at=started_at, status="failed", app_version=app_version)
        raise
