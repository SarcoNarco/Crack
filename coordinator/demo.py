"""Run the canonical, contained Crack MVP demonstration.

This module intentionally composes existing Python APIs.  It has no target,
provider, token, shell, Docker, browser, or network configuration surface.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol


_ROOT = Path(__file__).resolve().parents[1]
for _path in (_ROOT / "agents" / "router", _ROOT / "agents" / "mapper", _ROOT / "scope-controller"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agents.identity.agent import IdentityRunResult, run_identity
from agents.mapper.mapper.agent import AppContract, run_mapper
from agents.verifier.agent import VerificationResult, run_verifier
from coordinator.progress import ProgressCallback, notify
from model_router import ModelRouterError, get_client
from reports.generate import generate
from scope_controller import call_app_endpoint, reset_environment
from ui.run_view import format_run
from ledger.read_view import read_run


_OUTPUT_ROOT = _ROOT / "demo" / "output"
_DATABASE_PATH = _ROOT / "data" / "ledger.db"
_MANIFEST_FIELDS = frozenset({
    "session_id", "stage_statuses", "contract_path", "route_count",
    "identity_run_id", "hypothesis_id", "verifier_run_id", "verifier_verdict",
    "finding_id", "reset_identifiers", "terminal_view_status", "markdown_path",
    "html_path", "report_hashes", "timestamps",
})


class DemoError(RuntimeError):
    """A fail-closed condition in the canonical demo workflow."""


class ClientFactory(Protocol):
    def __call__(self, role: str) -> object: ...


@dataclass(frozen=True)
class DemoDependencies:
    health_check: Callable[[], dict[str, object]] = lambda: call_app_endpoint(
        "GET", "/health", "token-teacher-fixed"
    )
    client_factory: ClientFactory = get_client
    mapper: Callable[..., AppContract] = run_mapper
    resetter: Callable[[], str] = reset_environment
    identity: Callable[..., IdentityRunResult] = run_identity
    verifier: Callable[..., VerificationResult] = run_verifier
    view_reader: Callable[[str, Path], object] = read_run
    view_formatter: Callable[[object], str] = format_run
    report_generator: Callable[..., tuple[Path, Path]] = generate
    preflight_metadata: Callable[[], dict[str, object]] | None = None
    source_reader: Callable[[str], str] | None = None
    endpoint_caller: Callable[[str, str, str], dict[str, object]] | None = None
    verifier_resetter: Callable[[], str] | None = None


@dataclass(frozen=True)
class DemoResult:
    session_id: str
    manifest_path: Path
    exit_code: int
    verifier_run_id: str | None
    verdict: str | None
    finding_id: str | None
    failure_stage: str | None = None
    markdown_path: Path | None = None
    html_path: Path | None = None
    report_hashes: dict[str, str] | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _session_id(value: str | None) -> str:
    if value is None:
        return f"demo:{uuid.uuid4()}"
    if not isinstance(value, str) or not value.startswith("demo:"):
        raise ValueError("demo session ID must be server-generated")
    try:
        parsed = uuid.UUID(value.removeprefix("demo:"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("demo session ID must be server-generated") from exc
    if parsed.version != 4 or value != f"demo:{parsed}":
        raise ValueError("demo session ID must be server-generated")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    if set(payload) - _MANIFEST_FIELDS:
        raise DemoError("manifest contains a disallowed field")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with open(descriptor, "w", encoding="utf-8", closefd=True) as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_manifest(path: Path, *, session_id: str, stages: dict[str, str], started: str,
                    contract_path: Path | None = None, route_count: int | None = None,
                    identity_run_id: str | None = None, hypothesis_id: str | None = None,
                    verifier: VerificationResult | None = None, identity_reset: str | None = None,
                    terminal_view_status: str = "not_started", markdown_path: Path | None = None,
                    html_path: Path | None = None, report_hashes: dict[str, str] | None = None) -> None:
    payload: dict[str, object] = {
        "session_id": session_id, "stage_statuses": stages,
        "contract_path": str(contract_path) if contract_path else None, "route_count": route_count,
        "identity_run_id": identity_run_id, "hypothesis_id": hypothesis_id,
        "verifier_run_id": verifier.run_id if verifier else None,
        "verifier_verdict": verifier.verdict if verifier else None,
        "finding_id": verifier.finding_id if verifier else None,
        "reset_identifiers": {"identity": identity_reset, "verifier_a": verifier.attempts[0].snapshot_id if verifier else None, "verifier_b": verifier.attempts[1].snapshot_id if verifier else None},
        "terminal_view_status": terminal_view_status,
        "markdown_path": str(markdown_path) if markdown_path else None,
        "html_path": str(html_path) if html_path else None,
        "report_hashes": report_hashes or {}, "timestamps": {"started": started, "finished": _now()},
    }
    _atomic_json(path, payload)


def _preflight(dependencies: DemoDependencies) -> tuple[dict[str, object], dict[str, object]]:
    binding: dict[str, object] = {}
    if dependencies.preflight_metadata is not None:
        try:
            binding = dependencies.preflight_metadata()
        except Exception as exc:
            raise DemoError("approved managed runtime binding is unavailable") from exc
        if (
            set(binding) != {
                "target_id", "snapshot_sha256", "runtime_status", "architecture_provenance",
            }
            or binding.get("target_id") != "crack-school-portal"
            or binding.get("runtime_status") != "running"
            or binding.get("architecture_provenance") != "source-derived approved snapshot"
            or not isinstance(binding.get("snapshot_sha256"), str)
            or len(binding["snapshot_sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in binding["snapshot_sha256"])
        ):
            raise DemoError("approved managed runtime binding is mismatched")
    try:
        health = dependencies.health_check()
    except Exception as exc:
        raise DemoError("fixed loopback app health check is unavailable") from exc
    if health.get("status_code") != 200:
        raise DemoError("fixed loopback app health check did not return HTTP 200")
    clients: dict[str, object] = {}
    for role in ("mapper", "identity", "verifier_a", "verifier_b"):
        try:
            clients[role] = dependencies.client_factory(role)
        except ModelRouterError as exc:
            raise DemoError(f"provider preflight blocked for {role}: {exc}") from exc
        except Exception as exc:
            raise DemoError(f"provider preflight blocked for {role}") from exc
    return clients, binding


def run_demo(*, dependencies: DemoDependencies | None = None, output_root: Path = _OUTPUT_ROOT,
             database_path: Path = _DATABASE_PATH, emit: Callable[[str], None] = print,
             progress: ProgressCallback | None = None, session_id: str | None = None) -> DemoResult:
    """Execute one exact-ID handoff chain and return nonzero unless fully verified."""
    deps = dependencies or DemoDependencies()
    session_id, started = _session_id(session_id), _now()
    session_dir = output_root / session_id
    manifest_path = session_dir / "manifest.json"
    stages = {name: "pending" for name in ("preflight", "mapper", "identity_reset", "identity", "verifier", "terminal_view", "reports", "stability")}
    contract_path: Path | None = None
    route_count: int | None = None
    identity_run_id: str | None = None
    hypothesis_id: str | None = None
    verifier_result: VerificationResult | None = None
    identity_reset: str | None = None
    markdown_path: Path | None = None
    html_path: Path | None = None
    hashes: dict[str, str] = {}
    terminal_status = "not_started"
    failure_stage = "preflight"
    current_progress_stage = "preflight"

    def publish(**event: object) -> None:
        nonlocal current_progress_stage
        current_progress_stage = str(event.get("stage", current_progress_stage))
        notify(progress, **event)  # type: ignore[arg-type]

    try:
        publish(
            event_type="preflight.started", stage="preflight", state="active",
            logical_role="coordinator", headline="Fixed preflight started",
            explanation=(
                "The coordinator is checking only the loopback demo app and the four "
                "committed model-role bindings."
            ),
        )
        clients, runtime_binding = _preflight(deps)
        stages["preflight"] = "completed"
        bindings = [
            " · ".join(
                value for value in (
                    role,
                    str(getattr(client, "provider", "configured")),
                    str(getattr(client, "model", "configured")),
                ) if value
            )
            for role, client in clients.items()
        ]
        publish(
            event_type="preflight.completed", stage="preflight", state="completed",
            logical_role="coordinator", headline="Fixed preflight completed",
            explanation=(
                "The local app responded and every committed logical role has a configured "
                "client. No target or provider was supplied by the browser."
            ),
            metadata={"role_bindings": bindings, **runtime_binding},
        )

        failure_stage = "mapper"
        contract_path = session_dir / "app_contract.json"
        publish(
            event_type="mapper.activated", stage="mapper", state="active",
            logical_role="mapper", headline="Source-only mapper activated",
            explanation=(
                "The mapper is reading only the fixed source allowlist through the existing "
                "scope controller."
            ),
        )
        mapper_arguments: dict[str, object] = {
            "client": clients["mapper"], "output_path": contract_path,
        }
        if deps.source_reader is not None:
            mapper_arguments["source_reader"] = deps.source_reader
        contract = deps.mapper(**mapper_arguments)
        route_count = len(contract.routes)
        stages["mapper"] = "completed"
        publish(
            event_type="mapper.completed", stage="mapper", state="completed",
            logical_role="mapper", headline="Application contract validated",
            explanation=(
                "The model-produced map passed the existing schema and was written to this "
                "ignored demo session."
            ),
            metadata={"route_count": route_count},
            reference=f"demo://{session_id}/app-contract",
        )

        failure_stage = "identity_reset"
        publish(
            event_type="identity_reset.started", stage="authorization", state="active",
            logical_role="coordinator", headline="Authorization reset started",
            explanation="The disposable app is returning to its fixed seeded state.",
        )
        identity_reset = deps.resetter()
        stages["identity_reset"] = "completed"
        publish(
            event_type="identity_reset.completed", stage="authorization", state="active",
            logical_role="coordinator", headline="Authorization reset completed",
            explanation=(
                "A unique reset operation restored the same synthetic Teacher, Student A, "
                "Student B, class, assignment, submission, and grade fixtures."
            ),
            metadata={
                "reset_id": identity_reset,
                "state_hash": identity_reset.rsplit(":state-sha256:", 1)[-1],
            },
            reference=f"scope-controller://reset_environment/{identity_reset}",
        )

        failure_stage = "identity"
        publish(
            event_type="identity.activated", stage="authorization", state="active",
            logical_role="identity", headline="Authorization tester activated",
            explanation=(
                "The logical identity role will make at most the two existing normal-flow GET "
                "calls selected by bounded code."
            ),
        )
        identity_arguments: dict[str, object] = {
            "client": clients["identity"], "contract_path": contract_path,
        }
        if deps.endpoint_caller is not None:
            identity_arguments["endpoint_caller"] = deps.endpoint_caller
        if progress is not None:
            identity_arguments["progress"] = publish
        identity = deps.identity(**identity_arguments)
        identity_run_id = identity.run_id
        if len(identity.hypothesis_ids) != 1:
            raise DemoError("identity stage returned not exactly one hypothesis")
        hypothesis_id = identity.hypothesis_ids[0]
        stages["identity"] = "completed"
        publish(
            event_type="identity.completed", stage="authorization", state="completed",
            logical_role="identity", headline="Authorization test completed",
            explanation=(
                "The bounded Student B discovery to exact-submission detail request by Student A "
                "completed and produced one unverified hypothesis for independent checking."
            ),
            metadata={"identity_run_id": identity_run_id, "hypothesis_id": hypothesis_id},
            reference=f"ledger://hypothesis/{hypothesis_id}",
        )

        failure_stage = "verifier"
        verifier_arguments: dict[str, object] = {
            "client_a": clients["verifier_a"], "client_b": clients["verifier_b"],
        }
        if deps.endpoint_caller is not None:
            verifier_arguments["endpoint_caller"] = deps.endpoint_caller
        if deps.verifier_resetter is not None:
            verifier_arguments["resetter"] = deps.verifier_resetter
        if progress is not None:
            verifier_arguments["progress"] = publish
        verifier_result = deps.verifier(hypothesis_id, **verifier_arguments)
        if verifier_result.hypothesis_id != hypothesis_id:
            raise DemoError("verifier returned a different hypothesis ID")
        stages["verifier"] = "completed"
        if verifier_result.verdict == "verified" and not verifier_result.finding_id:
            raise DemoError("verified verdict has no finding ID")

        failure_stage = "terminal_view"
        emit(deps.view_formatter(deps.view_reader(verifier_result.run_id, database_path)).rstrip())
        terminal_status = "completed"
        stages["terminal_view"] = "completed"

        failure_stage = "reports"
        publish(
            event_type="report.started", stage="report", state="active",
            logical_role="reporter", headline="Deterministic report generation started",
            explanation=(
                "The report renderer is reading the exact completed verifier run from the "
                "ledger; it does not rerun any model or application call."
            ),
            metadata={"verifier_run_id": verifier_result.run_id},
            reference=f"ledger://run/{verifier_result.run_id}",
        )
        view = deps.view_reader(verifier_result.run_id, database_path)
        markdown_path, html_path = deps.report_generator(view)
        stages["reports"] = "completed"

        failure_stage = "stability"
        first_hashes = {"markdown": _sha256(markdown_path), "html": _sha256(html_path)}
        repeated_markdown, repeated_html = deps.report_generator(view)
        if (markdown_path, html_path) != (repeated_markdown, repeated_html):
            raise DemoError("repeat report generation returned different artifact paths")
        hashes = {"markdown": _sha256(markdown_path), "html": _sha256(html_path)}
        if hashes != first_hashes:
            raise DemoError("repeat report generation was not byte-stable")
        stages["stability"] = "completed"
    except Exception as exc:
        stages[failure_stage] = "failed"
        _write_manifest(manifest_path, session_id=session_id, stages=stages, started=started,
                        contract_path=contract_path, route_count=route_count, identity_run_id=identity_run_id,
                        hypothesis_id=hypothesis_id, verifier=verifier_result, identity_reset=identity_reset,
                        terminal_view_status=terminal_status, markdown_path=markdown_path, html_path=html_path,
                        report_hashes=hashes)
        detail = str(exc) if isinstance(exc, DemoError) else type(exc).__name__
        emit(f"DEMO FAILED: {failure_stage}: {detail}")
        publish(
            event_type="session.failed", stage=current_progress_stage, state="failed",
            logical_role="coordinator", headline="Contained run stopped safely",
            explanation=(
                "The current stage did not complete, so downstream stages were not activated "
                "and no result was invented."
            ),
            metadata={"failed_stage": current_progress_stage, "error_code": "stage_execution_failed"},
        )
        return DemoResult(session_id, manifest_path, 2, verifier_result.run_id if verifier_result else None,
                          verifier_result.verdict if verifier_result else None,
                          verifier_result.finding_id if verifier_result else None,
                          current_progress_stage, markdown_path, html_path, hashes)

    success = verifier_result is not None and verifier_result.verdict == "verified" and verifier_result.finding_id is not None
    if not success:
        stages["verifier"] = "completed_not_verified"
    _write_manifest(manifest_path, session_id=session_id, stages=stages, started=started,
                    contract_path=contract_path, route_count=route_count, identity_run_id=identity_run_id,
                    hypothesis_id=hypothesis_id, verifier=verifier_result, identity_reset=identity_reset,
                    terminal_view_status=terminal_status, markdown_path=markdown_path, html_path=html_path,
                    report_hashes=hashes)
    report_url = f"/api/demo-runs/{session_id}/report"
    publish(
        event_type="report.generated", stage="report", state="completed",
        logical_role="reporter", headline="Deterministic report generated",
        explanation=(
            "Markdown and standalone JavaScript-free HTML were generated twice with identical "
            "bytes from the exact verifier run."
        ),
        metadata={
            "markdown_sha256": hashes.get("markdown"),
            "html_sha256": hashes.get("html"),
            "report_url": report_url,
            "verifier_run_id": verifier_result.run_id if verifier_result else None,
        },
        reference=f"report://{verifier_result.run_id if verifier_result else 'unavailable'}",
    )
    publish(
        event_type="session.completed", stage="session", state="completed",
        logical_role="coordinator", headline="Contained verification run completed",
        explanation=(
            "The fixed workflow finished. Its verdict and any finding remain code-owned ledger "
            "facts, while this stream is only their presentation layer."
        ),
        metadata={
            "verdict": verifier_result.verdict if verifier_result else None,
            "verifier_run_id": verifier_result.run_id if verifier_result else None,
            "finding_id": verifier_result.finding_id if verifier_result else None,
            "report_url": report_url,
        },
        reference=f"ledger://run/{verifier_result.run_id if verifier_result else 'unavailable'}",
    )
    if success:
        emit(f"DEMO VERIFIED: session={session_id} verifier_run={verifier_result.run_id} finding={verifier_result.finding_id}")
        emit(f"Artifacts: {markdown_path} | {html_path} | {manifest_path}")
        return DemoResult(session_id, manifest_path, 0, verifier_result.run_id,
                          verifier_result.verdict, verifier_result.finding_id, None,
                          markdown_path, html_path, hashes)
    emit(f"DEMO COMPLETED BUT NOT VERIFIED: verdict={verifier_result.verdict if verifier_result else 'unknown'}")
    return DemoResult(session_id, manifest_path, 1, verifier_result.run_id if verifier_result else None,
                      verifier_result.verdict if verifier_result else None,
                      verifier_result.finding_id if verifier_result else None, None,
                      markdown_path, html_path, hashes)


def main() -> int:
    return run_demo().exit_code


if __name__ == "__main__":
    raise SystemExit(main())
