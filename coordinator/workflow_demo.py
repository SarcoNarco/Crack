"""Compose the bounded Sprint 7 workflow flow without changing the authorization demo."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


_ROOT = Path(__file__).resolve().parents[1]
for _path in (_ROOT / "agents" / "router", _ROOT / "agents" / "mapper", _ROOT / "scope-controller"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agents.mapper.mapper.agent import AppContract, run_mapper
from agents.verifier.agent import VerificationResult, run_verifier
from agents.workflow.agent import WorkflowRunResult, run_workflow
from coordinator.demo import DemoError
from model_router import ModelRouterError, get_client
from scope_controller import call_app_endpoint, reset_environment


_OUTPUT_ROOT = _ROOT / "demo" / "output"


class ClientFactory(Protocol):
    def __call__(self, role: str) -> object: ...


@dataclass(frozen=True)
class WorkflowDemoDependencies:
    health_check: Callable[[], dict[str, object]] = lambda: call_app_endpoint(
        "GET", "/health", "token-account-a-fixed"
    )
    client_factory: ClientFactory = get_client
    mapper: Callable[..., AppContract] = run_mapper
    resetter: Callable[[], str] = reset_environment
    workflow: Callable[..., WorkflowRunResult] = run_workflow
    verifier: Callable[..., VerificationResult] = run_verifier


@dataclass(frozen=True)
class WorkflowDemoResult:
    session_id: str
    mapper_route_count: int
    workflow_run_id: str
    hypothesis_id: str
    verifier_run_id: str
    verdict: str
    finding_id: str | None


def _session_id() -> str:
    return f"workflow-demo:{uuid.uuid4()}"


def _preflight(dependencies: WorkflowDemoDependencies) -> dict[str, object]:
    try:
        health = dependencies.health_check()
    except Exception as exc:
        raise DemoError("fixed loopback app health check is unavailable") from exc
    if health.get("status_code") != 200:
        raise DemoError("fixed loopback app health check did not return HTTP 200")
    clients: dict[str, object] = {}
    for role in ("mapper", "workflow", "verifier_a", "verifier_b"):
        try:
            clients[role] = dependencies.client_factory(role)
        except ModelRouterError as exc:
            raise DemoError(f"provider preflight blocked for {role}: {exc}") from exc
        except Exception as exc:
            raise DemoError(f"provider preflight blocked for {role}") from exc
    return clients


def run_workflow_demo(
    *, dependencies: WorkflowDemoDependencies | None = None, output_root: Path = _OUTPUT_ROOT
) -> WorkflowDemoResult:
    """Execute one exact-ID workflow handoff; reports and the authorization console stay out of scope."""
    dependencies = dependencies or WorkflowDemoDependencies()
    session_id = _session_id()
    clients = _preflight(dependencies)
    contract_path = output_root / session_id / "app_contract.json"
    contract = dependencies.mapper(client=clients["mapper"], output_path=contract_path)
    dependencies.resetter()
    workflow = dependencies.workflow(client=clients["workflow"], contract_path=contract_path)
    if len(workflow.hypothesis_ids) != 1:
        raise DemoError("workflow stage returned not exactly one hypothesis")
    verifier = dependencies.verifier(
        workflow.hypothesis_ids[0], client_a=clients["verifier_a"], client_b=clients["verifier_b"]
    )
    return WorkflowDemoResult(
        session_id=session_id,
        mapper_route_count=len(contract.routes),
        workflow_run_id=workflow.run_id,
        hypothesis_id=workflow.hypothesis_ids[0],
        verifier_run_id=verifier.run_id,
        verdict=verifier.verdict,
        finding_id=verifier.finding_id,
    )


def main() -> int:
    try:
        result = run_workflow_demo()
    except DemoError as exc:
        print(f"WORKFLOW DEMO BLOCKED: {exc}")
        return 2
    except Exception as exc:
        print(f"WORKFLOW DEMO FAILED: {exc}")
        return 1
    print(f"WORKFLOW DEMO {result.verdict.upper()}: {result.verifier_run_id}")
    return 0 if result.verdict == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
