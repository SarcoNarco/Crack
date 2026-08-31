from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from coordinator.runtime_binding import RuntimeBinding, RuntimeBindingError
from coordinator.runtime_main import runtime_dependencies
from targets.runtime import RuntimeHandoffError, RuntimeStatus


def _active(marker: str = "stable") -> object:
    return SimpleNamespace(
        marker=marker,
        plan=SimpleNamespace(
            manifest=SimpleNamespace(target_id="crack-school-portal"),
            snapshot_sha256="a" * 64,
        ),
    )


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.state_hash = "b" * 16

    def require_running(self) -> RuntimeStatus:
        self.calls.append("attest")
        return RuntimeStatus("running", "a" * 64, "crack-school-portal")

    def reset_disposable_state(self) -> RuntimeStatus:
        self.calls.append("reset")
        return RuntimeStatus(
            "running", "a" * 64, "crack-school-portal", self.state_hash,
        )


def test_preflight_is_lazy_and_emits_only_safe_binding_facts() -> None:
    runtime = FakeRuntime()
    active = _active()
    binding = RuntimeBinding(
        runtime=runtime, active_loader=lambda: active,
        architecture_builder=lambda: {
            "target": {"id": "crack-school-portal", "snapshot_sha256": "a" * 64},
        },
    )

    assert runtime.calls == []
    assert binding.preflight_metadata() == {
        "target_id": "crack-school-portal",
        "snapshot_sha256": "a" * 64,
        "runtime_status": "running",
        "architecture_provenance": "source-derived approved snapshot",
    }
    assert runtime.calls == ["attest", "attest"]


def test_source_reader_allows_only_mapper_files_and_rechecks_identity() -> None:
    runtime = FakeRuntime()
    stable = _active()
    changed = _active("changed")
    values = iter((stable, stable, changed, changed))
    binding = RuntimeBinding(
        runtime=runtime,
        active_loader=lambda: next(values),
        source_loader=lambda _active, _path: b"safe source",
    )

    with pytest.raises(RuntimeBindingError, match="changed during operation"):
        binding.read_source("app/main.py")

    untouched = RuntimeBinding(runtime=FakeRuntime(), active_loader=lambda: stable)
    with pytest.raises(RuntimeBindingError, match="not allowlisted"):
        untouched.read_source("README.md")
    assert untouched._runtime.calls == []


def test_endpoint_failure_is_sanitized_and_rechecked() -> None:
    runtime = FakeRuntime()
    active = _active()
    binding = RuntimeBinding(
        runtime=runtime,
        active_loader=lambda: active,
        endpoint_caller=lambda _method, _path, _token: (_ for _ in ()).throw(
            RuntimeError("secret response body")
        ),
    )

    with pytest.raises(RuntimeBindingError, match="did not complete") as error:
        binding.call_endpoint("GET", "/health", "token-teacher-fixed")

    assert "secret response body" not in str(error.value)
    assert runtime.calls == ["attest", "attest"]


def test_reset_uses_runtime_fingerprint_and_unique_operation_ids() -> None:
    runtime = FakeRuntime()
    active = _active()
    binding = RuntimeBinding(runtime=runtime, active_loader=lambda: active)

    first = binding.reset()
    second = binding.reset()

    assert first != second
    assert first.endswith(":state-sha256:" + "b" * 16)
    assert second.endswith(":state-sha256:" + "b" * 16)
    assert runtime.calls.count("reset") == 2
    assert not hasattr(runtime, "start") and not hasattr(runtime, "stop")


def test_reset_fails_closed_on_runtime_error_or_bad_fingerprint() -> None:
    active = _active()
    runtime = FakeRuntime()
    runtime.state_hash = "not-a-hash"
    binding = RuntimeBinding(runtime=runtime, active_loader=lambda: active)
    with pytest.raises(RuntimeBindingError, match="state is invalid"):
        binding.reset()

    runtime = FakeRuntime()
    runtime.reset_disposable_state = lambda: (_ for _ in ()).throw(
        RuntimeHandoffError("docker secret")
    )
    binding = RuntimeBinding(runtime=runtime, active_loader=lambda: active)
    with pytest.raises(RuntimeBindingError, match="did not complete") as error:
        binding.reset()
    assert "docker secret" not in str(error.value)


def test_runtime_dependency_factory_wires_only_bound_callables(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(
        read_source=lambda _path: "source",
        call_endpoint=lambda _method, _path, _token: {"status_code": 200},
        reset=lambda: "reset:00000000-0000-4000-8000-000000000000:state-sha256:" + "b" * 16,
        preflight_metadata=lambda: {
            "target_id": "crack-school-portal", "snapshot_sha256": "a" * 64,
            "runtime_status": "running",
            "architecture_provenance": "source-derived approved snapshot",
        },
    )
    monkeypatch.setattr("coordinator.runtime_main.RuntimeBinding", lambda: fake)

    dependencies = runtime_dependencies()

    assert dependencies.source_reader is fake.read_source
    assert dependencies.endpoint_caller is fake.call_endpoint
    assert dependencies.resetter is fake.reset
    assert dependencies.verifier_resetter is fake.reset
    assert dependencies.preflight_metadata is fake.preflight_metadata
    assert dependencies.health_check() == {"status_code": 200}


def test_runtime_entrypoint_has_fixed_host_and_no_target_options() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("runtime_main.py").read_text(
        encoding="utf-8"
    )
    assert 'host="127.0.0.1"' in source and "port=8000" in source
    assert "argparse" not in source and "target_host" not in source
