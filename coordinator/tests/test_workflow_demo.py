from __future__ import annotations

from pathlib import Path

import pytest

from agents.mapper.mapper.agent import AppContract
from agents.verifier.agent import VerificationResult
from agents.workflow.agent import WorkflowRunResult
from coordinator.demo import DemoError
from coordinator.workflow_demo import WorkflowDemoDependencies, run_workflow_demo


def _contract() -> AppContract:
    return AppContract.model_validate(
        {
            "routes": [{"method": "GET", "path": "/grades/mine", "description": "List"}],
            "roles": ["Teacher"],
            "assumptions": [],
            "workflow_rules": [],
        }
    )


def test_workflow_demo_uses_exact_handoff_without_the_authorization_console(tmp_path: Path) -> None:
    calls: list[str] = []

    def mapper(**kwargs: object) -> AppContract:
        calls.append("mapper")
        assert isinstance(kwargs["output_path"], Path)
        return _contract()

    def workflow(**kwargs: object) -> WorkflowRunResult:
        calls.append("workflow")
        assert kwargs["contract_path"].name == "app_contract.json"
        return WorkflowRunResult("workflow:one", [], ["workflow-hypothesis"], ["claim"], False)

    result = run_workflow_demo(
        dependencies=WorkflowDemoDependencies(
            health_check=lambda: {"status_code": 200},
            client_factory=lambda role: f"client:{role}",
            mapper=mapper,
            resetter=lambda: calls.append("reset") or "reset:one:state-sha256:same",
            workflow=workflow,
            verifier=lambda hypothesis_id, **kwargs: (
                calls.append("verifier")
                or VerificationResult("verifier:one", hypothesis_id, (), "verified", "finding-one")
            ),
        ),
        output_root=tmp_path,
    )

    assert calls == ["mapper", "reset", "workflow", "verifier"]
    assert result.hypothesis_id == "workflow-hypothesis"
    assert result.verdict == "verified"


def test_workflow_demo_fails_closed_without_exactly_one_hypothesis(tmp_path: Path) -> None:
    with pytest.raises(DemoError, match="not exactly one hypothesis"):
        run_workflow_demo(
            dependencies=WorkflowDemoDependencies(
                health_check=lambda: {"status_code": 200},
                client_factory=lambda role: f"client:{role}",
                mapper=lambda **_kwargs: _contract(),
                resetter=lambda: "reset:one:state-sha256:same",
                workflow=lambda **_kwargs: WorkflowRunResult("workflow:one", [], [], [], False),
                verifier=lambda *_args, **_kwargs: pytest.fail("verifier must not run"),
            ),
            output_root=tmp_path,
        )
