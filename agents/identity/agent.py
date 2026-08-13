"""Run one bounded, contract-driven cross-account authorization check."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ledger.init_db import record_run
from model_router import ModelClient, get_client
from scope_controller import call_app_endpoint, record_evidence, submit_hypothesis


_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "mapper" / "output" / "app_contract.json"
_LEDGER_DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "ledger.db"
_MAX_ENDPOINT_CALLS = 5
_ACCOUNT_A_TOKEN = "token-account-a-fixed"
_ACCOUNT_B_TOKEN = "token-account-b-fixed"
_DECLARED_SCOPE = "bounded contract-derived Account A to Account B authorization checks"
_STRUCTURED_OUTPUT = {"type": "json_object"}


class ContractRoute(BaseModel):
    method: str = Field(min_length=1)
    path: str = Field(min_length=1)
    description: str = Field(min_length=1)


class AppContract(BaseModel):
    routes: list[ContractRoute]
    roles: list[str]
    assumptions: list[str]


class IdentityPlan(BaseModel):
    """The model may select only a declared record-by-ID route, never IDs or calls."""

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
    as_account: str
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


def _records_routes(contract: AppContract) -> list[ContractRoute]:
    return [
        route
        for route in contract.routes
        if route.method.upper() == "GET" and "/records/" in route.path and "{" in route.path
    ]


def _my_records_route(contract: AppContract) -> ContractRoute | None:
    return next(
        (
            route
            for route in contract.routes
            if route.method.upper() == "GET" and route.path == "/records/mine"
        ),
        None,
    )


def _planner_prompt(contract: AppContract) -> str:
    record_routes = [route.model_dump() for route in _records_routes(contract)]
    contract_json = contract.model_dump_json(indent=2)
    return (
        "You are selecting the record-by-ID route for a contained authorization test. Work only "
        "from this app contract. Return only JSON matching exactly "
        '{"boundary_route":"/records/{record_id}"}. Select one listed GET route that contains '
        "{record_id}; do not select IDs, accounts, calls, writes, login, or routes outside the "
        "following choices: "
        f"{json.dumps(record_routes)}.\n\nAPP CONTRACT:\n{contract_json}"
    )


def _hypothesis_prompt(*, method: str, route: str, record_id: str) -> str:
    return (
        "You are wording an unverified authorization hypothesis for a contained demo app. "
        "The code observed that Account A received a successful response for a record which "
        f"Account B had just observed as its own, via {method} {route.replace('{record_id}', record_id)}. "
        "Return only JSON exactly shaped as "
        '{"concise_claim":"...","expected_evidence":"..."}. '
        "State the route and missing ownership boundary precisely. Do not call it verified and "
        "do not add severity or remediation claims."
    )


def _parse_model_json(raw_response: str, schema: type[BaseModel]) -> BaseModel:
    """Validate JSON after removing one complete Qwen reasoning prefix, if present."""
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
    """Resolve a declared record template from the model's template or concrete example."""
    for route in _records_routes(contract):
        if planned_path == route.path:
            return route
        pattern = re.escape(route.path).replace(
            re.escape("{record_id}"), r"[A-Za-z0-9_-]{1,100}"
        )
        if re.fullmatch(pattern, planned_path):
            return route
    return None


def _safe_record_id(value: str | None) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        return None
    return value


def _find_first(body: object, keys: set[str]) -> object | None:
    if isinstance(body, dict):
        for key, value in body.items():
            if key.lower() in keys and value is not None:
                return value
        for value in body.values():
            found = _find_first(value, keys)
            if found is not None:
                return found
    elif isinstance(body, list):
        for value in body:
            found = _find_first(value, keys)
            if found is not None:
                return found
    return None


def _account_b_record_id(response: dict[str, object]) -> str | None:
    body = response.get("body")
    owner = _find_first(
        body, {"owner", "owner_id", "owner_account_id", "account", "account_id"}
    )
    record_id = _find_first(body, {"id", "record_id"})
    if _normalise_identity(owner) != "accountb":
        return None
    return _safe_record_id(str(record_id))


def _cross_account_success(response: dict[str, object], account_b_record_id: str) -> bool:
    status_code = response.get("status_code")
    if not isinstance(status_code, int) or not 200 <= status_code < 300:
        return False
    body = response.get("body")
    response_id = _safe_record_id(str(_find_first(body, {"id", "record_id"})))
    owner = _find_first(
        body, {"owner", "owner_id", "owner_account_id", "account", "account_id"}
    )
    return response_id == account_b_record_id and _normalise_identity(owner) == "accountb"


def _response_summary(response: dict[str, object] | None, result: str) -> str:
    if response is None:
        return json.dumps({"result": result}, sort_keys=True)
    return json.dumps(
        {"result": result, "status_code": response.get("status_code")}, sort_keys=True
    )


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
) -> IdentityRunResult:
    """Execute one LLM-planned pass, with a hard cap of five app calls."""
    started_at = datetime.now(UTC).isoformat()
    run_id = f"identity:{uuid.uuid4()}"
    contract = _load_contract(contract_path)
    app_version = f"contract-sha256:{hashlib.sha256(contract.model_dump_json().encode()).hexdigest()[:16]}"
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
        discovery_route = _my_records_route(contract)
        boundary_route = _contract_route_for(plan.boundary_route, contract)
        if discovery_route is None or boundary_route is None:
            raise IdentityError(
                "App contract must declare GET /records/mine and a GET /records/{record_id} route"
            )

        discovery_response = endpoint_caller("GET", discovery_route.path, _ACCOUNT_B_TOKEN)
        account_b_record_id = _account_b_record_id(discovery_response)
        discovery_result = (
            "observed Account B-owned record"
            if account_b_record_id is not None
            else "did not observe an Account B-owned record"
        )
        discovery_status = discovery_response.get("status_code")
        tests.append(
            TestResult(
                "GET", discovery_route.path, "account_b", "observe_account_b_record",
                discovery_status if isinstance(discovery_status, int) else None, discovery_result,
            )
        )
        evidence_recorder(
            run_id=run_id, sequence_number=1, action_type="identity_test_result",
            request_response_summary=_response_summary(discovery_response, discovery_result),
            artifact_reference=f"scope-controller://call_app_endpoint/GET{discovery_route.path}",
            policy_decision="allowed",
        )

        if account_b_record_id is not None:
            boundary_path = boundary_route.path.replace("{record_id}", account_b_record_id)
            boundary_response = endpoint_caller("GET", boundary_path, _ACCOUNT_A_TOKEN)
            boundary_result = (
                "boundary violation: Account A received Account B record"
                if _cross_account_success(boundary_response, account_b_record_id)
                else "no cross-account boundary violation observed"
            )
            boundary_status = boundary_response.get("status_code")
            tests.append(
                TestResult(
                    "GET", boundary_path, "account_a", "cross_account_boundary",
                    boundary_status if isinstance(boundary_status, int) else None, boundary_result,
                )
            )
            evidence_recorder(
                run_id=run_id, sequence_number=2, action_type="identity_test_result",
                request_response_summary=_response_summary(boundary_response, boundary_result),
                artifact_reference=f"scope-controller://call_app_endpoint/GET{boundary_path}",
                policy_decision="allowed",
            )

            if boundary_result.startswith("boundary violation"):
                wording = _parse_model_json(
                    model_client.complete(
                        [{"role": "user", "content": _hypothesis_prompt(
                            method="GET", route=boundary_route.path, record_id=account_b_record_id
                        )}],
                        response_format=_STRUCTURED_OUTPUT,
                    ),
                    HypothesisWording,
                )
                assert isinstance(wording, HypothesisWording)
                hypothesis_id = hypothesis_submitter(
                    run_id,
                    f"GET {boundary_route.path} must enforce record ownership",
                    wording.concise_claim,
                    wording.expected_evidence,
                )
                hypothesis_ids.append(hypothesis_id)
                hypothesis_claims.append(wording.concise_claim)

        run_recorder(run_id=run_id, started_at=started_at, status="completed", app_version=app_version)
        return IdentityRunResult(run_id, tests, hypothesis_ids, hypothesis_claims, False)
    except Exception:
        run_recorder(run_id=run_id, started_at=started_at, status="failed", app_version=app_version)
        raise
