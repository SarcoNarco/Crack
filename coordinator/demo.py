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
        "GET", "/health", "token-account-a-fixed"
    )
    client_factory: ClientFactory = get_client
    mapper: Callable[..., AppContract] = run_mapper
    resetter: Callable[[], str] = reset_environment
    identity: Callable[..., IdentityRunResult] = run_identity
    verifier: Callable[..., VerificationResult] = run_verifier
    view_reader: Callable[[str, Path], object] = read_run
    view_formatter: Callable[[object], str] = format_run
    report_generator: Callable[..., tuple[Path, Path]] = generate


@dataclass(frozen=True)
class DemoResult:
    session_id: str
    manifest_path: Path
    exit_code: int
    verifier_run_id: str | None
    verdict: str | None
    finding_id: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


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


def _preflight(dependencies: DemoDependencies) -> dict[str, object]:
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
    return clients


def run_demo(*, dependencies: DemoDependencies | None = None, output_root: Path = _OUTPUT_ROOT,
             database_path: Path = _DATABASE_PATH, emit: Callable[[str], None] = print) -> DemoResult:
    """Execute one exact-ID handoff chain and return nonzero unless fully verified."""
    deps = dependencies or DemoDependencies()
    session_id, started = f"demo:{uuid.uuid4()}", _now()
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
    try:
        clients = _preflight(deps)
        stages["preflight"] = "completed"

        failure_stage = "mapper"
        contract_path = session_dir / "app_contract.json"
        contract = deps.mapper(client=clients["mapper"], output_path=contract_path)
        route_count = len(contract.routes)
        stages["mapper"] = "completed"

        failure_stage = "identity_reset"
        identity_reset = deps.resetter()
        stages["identity_reset"] = "completed"

        failure_stage = "identity"
        identity = deps.identity(client=clients["identity"], contract_path=contract_path)
        identity_run_id = identity.run_id
        if len(identity.hypothesis_ids) != 1:
            raise DemoError("identity stage returned not exactly one hypothesis")
        hypothesis_id = identity.hypothesis_ids[0]
        stages["identity"] = "completed"

        failure_stage = "verifier"
        verifier_result = deps.verifier(hypothesis_id, client_a=clients["verifier_a"], client_b=clients["verifier_b"])
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
        return DemoResult(session_id, manifest_path, 2, verifier_result.run_id if verifier_result else None,
                          verifier_result.verdict if verifier_result else None, verifier_result.finding_id if verifier_result else None)

    success = verifier_result is not None and verifier_result.verdict == "verified" and verifier_result.finding_id is not None
    if not success:
        stages["verifier"] = "completed_not_verified"
    _write_manifest(manifest_path, session_id=session_id, stages=stages, started=started,
                    contract_path=contract_path, route_count=route_count, identity_run_id=identity_run_id,
                    hypothesis_id=hypothesis_id, verifier=verifier_result, identity_reset=identity_reset,
                    terminal_view_status=terminal_status, markdown_path=markdown_path, html_path=html_path,
                    report_hashes=hashes)
    if success:
        emit(f"DEMO VERIFIED: session={session_id} verifier_run={verifier_result.run_id} finding={verifier_result.finding_id}")
        emit(f"Artifacts: {markdown_path} | {html_path} | {manifest_path}")
        return DemoResult(session_id, manifest_path, 0, verifier_result.run_id, verifier_result.verdict, verifier_result.finding_id)
    emit(f"DEMO COMPLETED BUT NOT VERIFIED: verdict={verifier_result.verdict if verifier_result else 'unknown'}")
    return DemoResult(session_id, manifest_path, 1, verifier_result.run_id if verifier_result else None,
                      verifier_result.verdict if verifier_result else None, verifier_result.finding_id if verifier_result else None)


def main() -> int:
    return run_demo().exit_code


if __name__ == "__main__":
    raise SystemExit(main())
