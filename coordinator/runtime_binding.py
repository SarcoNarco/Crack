"""Attested capabilities for the explicit managed-runtime console."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Final

from scope_controller import call_app_endpoint
from targets.active import ActiveTarget, ActiveTargetError, load_active_target, read_active_file
from targets.architecture import ArchitectureMapError, build_architecture_map
from targets.runtime import RuntimeHandoffError, RuntimeService, RuntimeStatus

_MAPPER_PATHS: Final = frozenset({"app/main.py", "scripts/seed.py", "app/database.py"})
_STATE_HASH: Final = re.compile(r"[0-9a-f]{16}")


class RuntimeBindingError(RuntimeError):
    """Safe runtime-binding failure."""


class RuntimeBinding:
    """Capture one active snapshot and attest each bound operation around use."""

    def __init__(self, *, runtime: RuntimeService | None = None,
                 active_loader: Callable[[], ActiveTarget] = load_active_target,
                 source_loader: Callable[[ActiveTarget, str], bytes] = read_active_file,
                 endpoint_caller: Callable[[str, str, str], dict[str, object]] = call_app_endpoint,
                 architecture_builder: Callable[[], dict[str, object]] = build_architecture_map) -> None:
        self._runtime = runtime or RuntimeService()
        self._active_loader = active_loader
        self._source_loader = source_loader
        self._endpoint_caller = endpoint_caller
        self._architecture_builder = architecture_builder
        self._active: ActiveTarget | None = None

    def read_source(self, path: str) -> str:
        if path not in _MAPPER_PATHS:
            raise RuntimeBindingError("runtime source path is not allowlisted")
        active = self._attest_captured()
        try:
            content = self._source_loader(active, path).decode("utf-8")
        except (ActiveTargetError, OSError, UnicodeDecodeError) as exc:
            raise RuntimeBindingError("runtime source is unavailable") from exc
        self._attest_captured()
        return content

    def call_endpoint(self, method: str, path: str, account_token: str) -> dict[str, object]:
        self._attest_captured()
        try:
            response = self._endpoint_caller(method, path, account_token)
        except Exception as exc:
            self._attest_captured()
            raise RuntimeBindingError("runtime endpoint call did not complete") from exc
        self._attest_captured()
        return response

    def reset(self) -> str:
        self._attest_captured()
        try:
            status = self._runtime.reset_disposable_state()
        except RuntimeHandoffError as exc:
            raise RuntimeBindingError("runtime reset did not complete") from exc
        if self._active is None or not _matches(status, self._active) or _STATE_HASH.fullmatch(status.state_hash or "") is None:
            raise RuntimeBindingError("runtime reset state is invalid")
        self._attest_captured()
        return f"reset:{uuid.uuid4()}:state-sha256:{status.state_hash}"

    def preflight_metadata(self) -> dict[str, object]:
        active = self._attest_captured()
        try:
            architecture = self._architecture_builder()
        except ArchitectureMapError as exc:
            raise RuntimeBindingError("runtime architecture provenance is unavailable") from exc
        if architecture.get("target") != {
            "id": active.plan.manifest.target_id,
            "snapshot_sha256": active.plan.snapshot_sha256,
        }:
            raise RuntimeBindingError("runtime architecture provenance is mismatched")
        self._attest_captured()
        return {"target_id": active.plan.manifest.target_id,
                "snapshot_sha256": active.plan.snapshot_sha256,
                "runtime_status": "running",
                "architecture_provenance": "source-derived approved snapshot"}

    def _attest_captured(self) -> ActiveTarget:
        active = self._attest_current()
        if self._active is None:
            self._active = active
        elif active != self._active:
            raise RuntimeBindingError("runtime approved target changed during operation")
        return active

    def _attest_current(self) -> ActiveTarget:
        try:
            active = self._active_loader()
            status = self._runtime.require_running()
            refreshed = self._active_loader()
        except (ActiveTargetError, RuntimeHandoffError) as exc:
            raise RuntimeBindingError("runtime binding is unavailable") from exc
        if active != refreshed or not _matches(status, active):
            raise RuntimeBindingError("runtime binding is mismatched")
        return active


def _matches(status: RuntimeStatus, active: ActiveTarget) -> bool:
    return (status.state == "running" and status.target_id == active.plan.manifest.target_id
            and status.snapshot_sha256 == active.plan.snapshot_sha256)
