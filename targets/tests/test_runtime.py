from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import targets.runtime as runtime_module
from targets.docker_adapter import (
    CONTAINER_NAME,
    DockerAdapter,
    DockerCommandError,
    IMAGE_NAME,
    NETWORK_NAME,
    _safe_output,
    required_labels,
)
from targets.inspection import TargetImportError, inspect_target
from targets.registry import register_approved
from targets.runtime import FIXED_DOCKERFILE_SHA256, RuntimeHandoffError, RuntimeService
from targets.runtime import _probe_loopback_health


ROOT = Path(__file__).resolve().parents[2]
IMAGE_ID = "sha256:" + "a" * 64
IMAGE_ENVIRONMENT = ["PATH=/usr/local/bin"]


def _image(labels: dict[str, str], *, image_id: str = IMAGE_ID) -> dict[str, object]:
    return {"Id": image_id, "Config": {"Labels": dict(labels), "Env": list(IMAGE_ENVIRONMENT)}}


def _container(labels: dict[str, str], *, image_id: str = IMAGE_ID, status: str = "running") -> dict[str, object]:
    return {
        "Name": f"/{CONTAINER_NAME}",
        "Image": image_id,
        "Config": {
            "Labels": labels,
            "User": "65534:65534",
            "Env": [*IMAGE_ENVIRONMENT, "APP_DB_PATH=/workspace/data/demo_app.db"],
            "Volumes": None,
        },
        "HostConfig": {
            "Privileged": False,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "Devices": None,
            "Binds": None,
            "NetworkMode": NETWORK_NAME,
            "ReadonlyRootfs": True,
            "SecurityOpt": ["no-new-privileges:true"],
            "PidsLimit": 128,
            "Memory": 256 * 1024 * 1024,
            "NanoCpus": 1_000_000_000,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "IpcMode": "private",
            "PidMode": "",
            "Tmpfs": {"/workspace/data": "rw,noexec,nosuid,mode=1777,size=16m"},
        },
        "NetworkSettings": {
            "Ports": {"8100/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8100"}]},
            "Networks": {NETWORK_NAME: {}},
        },
        "Mounts": [{"Type": "tmpfs", "Destination": "/workspace/data", "RW": True, "Source": ""}],
        "State": {"Status": status},
    }


def _network(labels: dict[str, str]) -> dict[str, object]:
    return {
        "Name": NETWORK_NAME,
        "Labels": labels,
        "Driver": "bridge",
        "Scope": "local",
        "Internal": True,
        "Attachable": False,
        "Ingress": False,
        "ConfigOnly": False,
    }


class FakeDocker:
    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = labels
        self.image_state: dict[str, object] | None = _image(labels)
        self.image_sequence: list[dict[str, object] | None] = []
        self.current_container: dict[str, object] | None = None
        self.current_network: dict[str, object] | None = None
        self.calls: list[str] = []
        self.fail_run = False
        self.state_fingerprint = "b" * 16

    def image(self) -> dict[str, object] | None:
        self.calls.append("image")
        if self.image_sequence:
            return self.image_sequence.pop(0)
        return self.image_state

    def container(self) -> dict[str, object] | None:
        self.calls.append("container")
        return self.current_container

    def network(self) -> dict[str, object] | None:
        self.calls.append("network")
        return self.current_network

    def create_network(self, snapshot_sha256: str, dockerfile_sha256: str) -> None:
        self.calls.append("create-network")
        self.current_network = _network(required_labels(snapshot_sha256, dockerfile_sha256))

    def run_container(self, image_id: str, snapshot_sha256: str, dockerfile_sha256: str) -> None:
        self.calls.append("run")
        if self.fail_run:
            raise DockerCommandError("run failed")
        self.current_container = _container(required_labels(snapshot_sha256, dockerfile_sha256), image_id=image_id)

    def seed_disposable_data(self) -> None:
        self.calls.append("seed")

    def seeded_state_fingerprint(self) -> str:
        self.calls.append("fingerprint")
        return self.state_fingerprint

    def remove_container(self) -> None:
        self.calls.append("remove-container")
        self.current_container = None

    def remove_network(self) -> None:
        self.calls.append("remove-network")
        self.current_network = None


def _registered_service(tmp_path: Path, *, health_probe: object | None = None) -> tuple[RuntimeService, FakeDocker, str, Path]:
    source = ROOT / "app-under-test"
    plan = inspect_target(source)
    registry = tmp_path / "registry"
    register_approved(source, plan.snapshot_sha256, registry_root=registry)
    fake = FakeDocker(required_labels(plan.snapshot_sha256, FIXED_DOCKERFILE_SHA256))
    probe = health_probe if health_probe is not None else (lambda: None)
    return RuntimeService(registry_root=registry, docker=fake, health_probe=probe), fake, plan.snapshot_sha256, registry


def test_start_uses_only_matching_preexisting_offline_image_and_fixed_resources(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)

    result = service.start(approved_hash)

    assert result.state == "started"
    assert result.snapshot_sha256 == approved_hash
    assert fake.calls == ["image", "container", "network", "create-network", "image", "run", "container", "seed"]
    assert fake.current_network and fake.current_network["Internal"] is True
    assert fake.current_container and fake.current_container["Config"]["Labels"] == fake.labels


def test_require_running_rechecks_managed_container_and_health(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    fake.current_network = _network(fake.labels)
    fake.current_container = _container(fake.labels)

    result = service.require_running()

    assert result == runtime_module.RuntimeStatus("running", approved_hash, "crack-school-portal")
    assert fake.calls == ["container", "network", "image", "container", "network", "image"]


def test_reset_running_runtime_returns_adapter_derived_logical_fingerprint(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    fake.current_network = _network(fake.labels)
    fake.current_container = _container(fake.labels)

    result = service.reset_disposable_state()

    assert result == runtime_module.RuntimeStatus("running", approved_hash, "crack-school-portal", "b" * 16)
    assert fake.calls == [
        "container", "network", "image", "container", "network", "image", "seed",
        "fingerprint", "container", "network", "image",
    ]


def test_reset_rejects_malformed_adapter_fingerprint(tmp_path: Path) -> None:
    service, fake, _approved_hash, _ = _registered_service(tmp_path)
    fake.current_network = _network(fake.labels)
    fake.current_container = _container(fake.labels)
    fake.state_fingerprint = "bad"

    with pytest.raises(RuntimeHandoffError, match="logical state fingerprint is malformed"):
        service.reset_disposable_state()
    assert "remove-container" not in fake.calls and "remove-network" not in fake.calls


def test_runtime_binding_rejects_active_metadata_replacement_after_health(tmp_path: Path) -> None:
    registry_holder: dict[str, Path] = {}

    def replace_active_metadata() -> None:
        active = registry_holder["registry"] / "active-target.json"
        replacement = active.with_name(".replacement-active-target.json")
        replacement.write_bytes(active.read_bytes())
        replacement.replace(active)

    service, fake, _, registry = _registered_service(tmp_path, health_probe=replace_active_metadata)
    registry_holder["registry"] = registry
    fake.current_network = _network(fake.labels)
    fake.current_container = _container(fake.labels)

    with pytest.raises(RuntimeHandoffError, match="active approved target changed"):
        service.require_running()


def test_reset_reinspects_exact_container_immediately_before_seed(tmp_path: Path) -> None:
    service, fake, _, _ = _registered_service(tmp_path)
    fake.current_network = _network(fake.labels)
    fake.current_container = _container(fake.labels)

    def replace_container_after_health() -> None:
        assert fake.current_container is not None
        fake.current_container = _container({**fake.labels, "io.crack.snapshot-sha256": "c" * 64})

    service._health_probe = replace_container_after_health

    with pytest.raises(RuntimeHandoffError, match="different approved hash"):
        service.reset_disposable_state()
    assert "seed" not in fake.calls


def test_start_rejects_approval_or_image_hash_mismatch(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)

    with pytest.raises(RuntimeHandoffError, match="approval hash"):
        service.start("a" * 64)
    assert fake.calls == []

    fake.image_state = _image(required_labels("b" * 64, FIXED_DOCKERFILE_SHA256))
    with pytest.raises(RuntimeHandoffError, match="local offline image"):
        service.start(approved_hash)
    assert "create-network" not in fake.calls

    fake.image_state = _image(fake.labels, image_id="not-an-image-id")
    with pytest.raises(RuntimeHandoffError, match="valid immutable ID"):
        service.start(approved_hash)
    assert "create-network" not in fake.calls


def test_metadata_snapshot_dockerfile_and_symlink_tamper_fail_before_docker(tmp_path: Path) -> None:
    service, fake, approved_hash, registry = _registered_service(tmp_path)
    active = registry / "active-target.json"
    metadata = json.loads(active.read_text(encoding="utf-8"))
    metadata["target_id"] = "other"
    active.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(RuntimeHandoffError, match="metadata"):
        service.status()
    assert fake.calls == []

    service, fake, _, registry = _registered_service(tmp_path / "metadata-link")
    active = registry / "active-target.json"
    active.unlink()
    active.symlink_to(registry / "snapshots")
    with pytest.raises(RuntimeHandoffError, match="metadata is unsafe"):
        service.status()
    assert fake.calls == []

    service, fake, approved_hash, registry = _registered_service(tmp_path / "changed")
    dockerfile = registry / "snapshots" / approved_hash / "Dockerfile"
    dockerfile.write_text("changed", encoding="utf-8")
    with pytest.raises(RuntimeHandoffError, match="hash changed"):
        service.start(approved_hash)
    assert fake.calls == []

    service, fake, approved_hash, registry = _registered_service(tmp_path / "linked")
    dockerfile = registry / "snapshots" / approved_hash / "Dockerfile"
    dockerfile.unlink()
    dockerfile.symlink_to(registry / "active-target.json")
    with pytest.raises(RuntimeHandoffError, match="unsafe or malformed"):
        service.status()
    assert fake.calls == []


def test_different_hash_container_or_network_is_refused(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    wrong_labels = required_labels("c" * 64, FIXED_DOCKERFILE_SHA256)
    fake.current_container = _container(wrong_labels)
    with pytest.raises(RuntimeHandoffError, match="different approved hash"):
        service.start(approved_hash)
    assert "remove-container" not in fake.calls

    service, fake, approved_hash, _ = _registered_service(tmp_path / "network")
    fake.current_network = {**_network(fake.labels), "Internal": False}
    with pytest.raises(RuntimeHandoffError, match="containment"):
        service.start(approved_hash)
    assert "run" not in fake.calls


def test_dockerfile_label_mismatch_and_registry_parent_symlink_are_refused(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    fake.image_state = _image(required_labels(approved_hash, "d" * 64))
    with pytest.raises(RuntimeHandoffError, match="local offline image"):
        service.start(approved_hash)

    service, fake, _, registry = _registered_service(tmp_path / "parent")
    alias_parent = tmp_path / "registry-parent-alias"
    alias_parent.symlink_to(registry.parent, target_is_directory=True)
    aliased_registry = alias_parent / registry.name
    aliased_service = RuntimeService(registry_root=aliased_registry, docker=fake, health_probe=lambda: None)
    with pytest.raises(RuntimeHandoffError, match="target registry is unsafe"):
        aliased_service.status()


def test_tag_retarget_or_deletion_between_inspection_and_run_is_refused(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    fake.image_sequence = [
        _image(fake.labels),
        _image(fake.labels, image_id="sha256:" + "b" * 64),
    ]
    with pytest.raises(RuntimeHandoffError, match="rolled back"):
        service.start(approved_hash)
    assert "run" not in fake.calls
    assert fake.current_network is None

    service, fake, approved_hash, _ = _registered_service(tmp_path / "deleted")
    fake.image_sequence = [_image(fake.labels), None]
    with pytest.raises(RuntimeHandoffError, match="rolled back"):
        service.start(approved_hash)
    assert "run" not in fake.calls
    assert fake.current_network is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda container: container["HostConfig"].update({"Privileged": True}),
        lambda container: container.update({"Mounts": []}),
        lambda container: container["HostConfig"].update({"NetworkMode": "host"}),
        lambda container: container.update({"Image": "sha256:" + "b" * 64}),
        lambda container: container["NetworkSettings"].update(
            {"Ports": {"8100/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8100"}]}}
        ),
        lambda container: container["Config"].update(
            {"Env": [*IMAGE_ENVIRONMENT, "APP_DB_PATH=/workspace/data/demo_app.db", "UNSAFE=1"]}
        ),
        lambda container: container["HostConfig"].update({"RestartPolicy": {"Name": "always", "MaximumRetryCount": 0}}),
    ],
    ids=("privileged", "mount", "host-network", "different-image", "non-loopback-port", "extra-env", "restart"),
)
def test_matching_labels_do_not_bypass_container_containment(
    tmp_path: Path, mutate: object
) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    forged = _container(fake.labels, status="exited")
    mutate(forged)  # type: ignore[operator]
    fake.current_container = forged

    with pytest.raises(RuntimeHandoffError, match="approved hash|containment|ownership"):
        service.start(approved_hash)
    assert "remove-container" not in fake.calls


@pytest.mark.parametrize("field", ("Attachable", "Ingress", "ConfigOnly", "Driver", "Scope"))
def test_matching_labels_do_not_bypass_network_containment(tmp_path: Path, field: str) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    invalid_value: object = "overlay" if field == "Driver" else ("swarm" if field == "Scope" else True)
    fake.current_network = {**_network(fake.labels), field: invalid_value}

    with pytest.raises(RuntimeHandoffError, match="containment"):
        service.start(approved_hash)
    assert "run" not in fake.calls


def test_created_container_is_reinspected_before_seed_and_bad_cleanup_is_reported(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    original_run = fake.run_container

    def forge_after_run(image_id: str, snapshot_sha256: str, dockerfile_sha256: str) -> None:
        original_run(image_id, snapshot_sha256, dockerfile_sha256)
        assert fake.current_container is not None
        fake.current_container["HostConfig"]["Binds"] = ["/host:/workspace"]

    fake.run_container = forge_after_run  # type: ignore[method-assign]
    with pytest.raises(RuntimeHandoffError, match="rollback incomplete"):
        service.start(approved_hash)
    assert "seed" not in fake.calls
    assert "remove-container" not in fake.calls


def test_partial_network_creation_is_inspected_and_rolled_back(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)

    def create_then_fail(snapshot_sha256: str, dockerfile_sha256: str) -> None:
        fake.calls.append("create-network")
        fake.current_network = _network(required_labels(snapshot_sha256, dockerfile_sha256))
        raise DockerCommandError("network create timed out")

    fake.create_network = create_then_fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeHandoffError, match="^fixed runtime start failed; rolled back new fixed resources$"):
        service.start(approved_hash)

    assert fake.calls == ["image", "container", "network", "create-network", "network", "remove-network"]
    assert fake.current_network is None
    assert fake.current_container is None


def test_partial_container_run_is_inspected_and_rolled_back_without_removing_preexisting_network(
    tmp_path: Path,
) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    fake.current_network = _network(fake.labels)

    def run_then_fail(image_id: str, snapshot_sha256: str, dockerfile_sha256: str) -> None:
        fake.calls.append("run")
        fake.current_container = _container(
            required_labels(snapshot_sha256, dockerfile_sha256), image_id=image_id
        )
        raise DockerCommandError("run timed out")

    fake.run_container = run_then_fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeHandoffError, match="^fixed runtime start failed; rolled back new fixed resources$"):
        service.start(approved_hash)

    assert "remove-container" in fake.calls
    assert "remove-network" not in fake.calls
    assert fake.current_container is None
    assert fake.current_network is not None


def test_existing_running_container_is_health_checked_before_idempotent_return(tmp_path: Path) -> None:
    probes: list[str] = []
    service, fake, approved_hash, _ = _registered_service(tmp_path, health_probe=lambda: probes.append("health"))
    service.start(approved_hash)
    assert service.start(approved_hash).state == "running"
    assert probes == ["health", "health"]


def test_health_failure_rolls_back_only_new_fixed_resources(tmp_path: Path) -> None:
    def fail_health() -> None:
        raise RuntimeHandoffError("health failed")

    service, fake, approved_hash, _ = _registered_service(tmp_path, health_probe=fail_health)
    with pytest.raises(RuntimeHandoffError, match="rolled back"):
        service.start(approved_hash)

    assert "remove-container" in fake.calls
    assert "remove-network" in fake.calls
    assert fake.current_container is None
    assert fake.current_network is None


def test_cleanup_failure_reports_incomplete_rollback(tmp_path: Path) -> None:
    def fail_health() -> None:
        raise RuntimeHandoffError("health failed")

    service, fake, approved_hash, _ = _registered_service(tmp_path, health_probe=fail_health)

    def fail_remove_container() -> None:
        fake.calls.append("remove-container")
        raise DockerCommandError("remove failed")

    fake.remove_container = fail_remove_container  # type: ignore[method-assign]
    with pytest.raises(RuntimeHandoffError, match="rollback incomplete"):
        service.start(approved_hash)


def test_failed_seed_keeps_preexisting_matching_network(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    fake.current_network = _network(fake.labels)

    def fail_seed() -> None:
        fake.calls.append("seed")
        raise DockerCommandError("seed failed")

    fake.seed_disposable_data = fail_seed  # type: ignore[method-assign]
    with pytest.raises(RuntimeHandoffError, match="rolled back"):
        service.start(approved_hash)
    assert fake.current_container is None
    assert fake.current_network is not None
    assert "remove-network" not in fake.calls


def test_status_and_stop_are_idempotent_for_only_matching_resources(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    assert service.status().state == "stopped"
    assert service.stop().state == "stopped"
    service.start(approved_hash)
    assert service.start(approved_hash).state == "running"
    assert service.status().state == "running"
    assert service.stop().state == "stopped"
    assert service.stop().state == "stopped"


def test_running_status_or_start_refuses_missing_or_uncontained_network(tmp_path: Path) -> None:
    service, fake, approved_hash, _ = _registered_service(tmp_path)
    fake.current_container = _container(fake.labels)

    with pytest.raises(RuntimeHandoffError, match="network is missing"):
        service.start(approved_hash)
    with pytest.raises(RuntimeHandoffError, match="network is missing"):
        service.status()

    fake.current_network = {**_network(fake.labels), "Internal": False}
    with pytest.raises(RuntimeHandoffError, match="containment"):
        service.start(approved_hash)
    with pytest.raises(RuntimeHandoffError, match="containment"):
        service.status()


def test_stop_is_idempotent_without_image_when_no_container_exists(tmp_path: Path) -> None:
    service, fake, _, _ = _registered_service(tmp_path)
    fake.image_state = None

    assert service.status().state == "stopped"
    assert service.stop().state == "stopped"


def test_public_runtime_methods_translate_docker_failures_without_output(tmp_path: Path) -> None:
    secret = "daemon-output-must-not-escape"

    service, fake, approved_hash, _ = _registered_service(tmp_path)

    def fail_image() -> None:
        raise DockerCommandError(secret)

    fake.image = fail_image  # type: ignore[method-assign]
    with pytest.raises(RuntimeHandoffError, match="^fixed Docker runtime operation failed$") as error:
        service.start(approved_hash)
    assert secret not in str(error.value)

    service, fake, approved_hash, _ = _registered_service(tmp_path / "network")

    def fail_network() -> None:
        raise DockerCommandError(secret)

    fake.network = fail_network  # type: ignore[method-assign]
    with pytest.raises(RuntimeHandoffError, match="^fixed Docker runtime operation failed$") as error:
        service.start(approved_hash)
    assert secret not in str(error.value)

    service, fake, _, _ = _registered_service(tmp_path / "stop")
    fake.current_container = _container(fake.labels, status="exited")
    fake.current_network = _network(fake.labels)

    def fail_remove_container() -> None:
        raise DockerCommandError(secret)

    fake.remove_container = fail_remove_container  # type: ignore[method-assign]
    with pytest.raises(RuntimeHandoffError, match="^fixed Docker runtime operation failed$") as error:
        service.stop()
    assert secret not in str(error.value)


def test_cli_renders_stable_safe_errors_for_daemon_inspection_and_removal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "daemon-output-must-not-escape"
    service, fake, _, _ = _registered_service(tmp_path)

    def fail_container() -> None:
        raise DockerCommandError(secret)

    fake.container = fail_container  # type: ignore[method-assign]
    monkeypatch.setattr(runtime_module, "RuntimeService", lambda: service)
    assert runtime_module.main(["status"]) == 2
    assert capsys.readouterr().out == "error: fixed Docker runtime operation failed\n"

    service, fake, approved_hash, _ = _registered_service(tmp_path / "removal")
    fake.current_container = _container(fake.labels, status="exited")
    fake.current_network = _network(fake.labels)

    def fail_remove_container() -> None:
        raise DockerCommandError(secret)

    fake.remove_container = fail_remove_container  # type: ignore[method-assign]
    monkeypatch.setattr(runtime_module, "RuntimeService", lambda: service)
    assert runtime_module.main(["start", "--approve-sha256", approved_hash]) == 2
    assert capsys.readouterr().out == "error: fixed Docker runtime operation failed\n"


def test_health_probe_retries_only_fixed_loopback_until_bounded_deadline() -> None:
    clock_value = [0.0]
    sleeps: list[float] = []
    attempts: list[object] = [OSError("not ready"), (503, b"wait"), (200, b'{"status":"ok"}')]

    class Connection:
        def __init__(self, action: object) -> None:
            self.action = action

        def request(self, method: str, path: str) -> None:
            assert (method, path) == ("GET", "/health")

        def getresponse(self) -> object:
            if isinstance(self.action, Exception):
                raise self.action
            status, body = self.action
            return SimpleNamespace(status=status, read=lambda _: body)

        def close(self) -> None:
            return None

    def factory(host: str, port: int, timeout: float) -> Connection:
        assert (host, port, timeout) == ("127.0.0.1", 8100, 0.1)
        return Connection(attempts.pop(0))

    def clock() -> float:
        return clock_value[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock_value[0] += seconds

    _probe_loopback_health(clock=clock, sleep=sleep, connection_factory=factory)
    assert sleeps == [0.1, 0.1]


def test_health_probe_fails_after_bounded_fixed_attempts() -> None:
    clock_value = [0.0]

    class Connection:
        def request(self, *_: object) -> None:
            return None

        def getresponse(self) -> object:
            return SimpleNamespace(status=503, read=lambda _: b"wait")

        def close(self) -> None:
            return None

    def sleep(seconds: float) -> None:
        clock_value[0] += seconds

    with pytest.raises(RuntimeHandoffError, match="health check failed"):
        _probe_loopback_health(
            clock=lambda: clock_value[0], sleep=sleep, connection_factory=lambda *_, **__: Connection()
        )


def test_docker_adapter_uses_exact_fixed_argv_and_sanitized_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(arguments: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("targets.docker_adapter.subprocess.run", fake_run)
    adapter = DockerAdapter()
    adapter.create_network("a" * 64, FIXED_DOCKERFILE_SHA256)
    adapter.run_container(IMAGE_ID, "a" * 64, FIXED_DOCKERFILE_SHA256)
    adapter.seed_disposable_data()

    network_argv, network_kwargs = calls[0]
    assert network_argv[0:3] == ("docker", "network", "create")
    assert "--driver" in network_argv and "bridge" in network_argv and "--internal" in network_argv
    assert network_kwargs["shell"] is False

    argv, kwargs = calls[1]
    assert argv[0:2] == ("docker", "run")
    assert argv[-1] == IMAGE_ID
    assert "--publish" in argv and "127.0.0.1:8100:8100" in argv
    assert "--network" in argv and NETWORK_NAME in argv
    assert "--read-only" in argv and "--cap-drop" in argv and "ALL" in argv
    assert "build" not in argv and "pull" not in argv and "compose" not in argv
    assert "--pull=never" in argv and "--restart" in argv and "no" in argv and "--user" in argv
    assert not {"--privileged", "--pid", "--ipc", "--device", "--cap-add", "--volume", "--mount"} & set(argv)
    assert kwargs["shell"] is False
    assert set(kwargs["env"]) == {"PATH", "LANG", "LC_ALL"}
    assert kwargs["cwd"] == str(ROOT)
    assert calls[2][0] == ("docker", "exec", CONTAINER_NAME, "python", "-m", "scripts.seed")


def test_docker_adapter_timeout_and_output_redaction_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_: object, **__: object) -> None:
        raise __import__("subprocess").TimeoutExpired("docker", 1)

    monkeypatch.setattr("targets.docker_adapter.subprocess.run", timeout)
    with pytest.raises(DockerCommandError, match="did not complete"):
        DockerAdapter().run_container(IMAGE_ID, "a" * 64, FIXED_DOCKERFILE_SHA256)

    assert "test-value" not in _safe_output("API_KEY=test-value")


def test_docker_adapter_fingerprint_uses_fixed_shell_free_program_and_validates_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def valid(arguments: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=0, stdout="b" * 16 + "\n", stderr="")

    monkeypatch.setattr("targets.docker_adapter.subprocess.run", valid)
    assert DockerAdapter().seeded_state_fingerprint() == "b" * 16
    argv, kwargs = calls[0]
    assert argv[:5] == ("docker", "exec", CONTAINER_NAME, "python", "-c")
    assert len(argv) == 6 and "sqlite3.connect('/workspace/data/demo_app.db')" in argv[-1]
    assert kwargs["shell"] is False and set(kwargs["env"]) == {"PATH", "LANG", "LC_ALL"}

    def malformed(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="unexpected-output-must-not-escape", stderr="")

    monkeypatch.setattr("targets.docker_adapter.subprocess.run", malformed)
    with pytest.raises(DockerCommandError, match="fingerprint was malformed") as error:
        DockerAdapter().seeded_state_fingerprint()
    assert "must-not-escape" not in str(error.value)


def test_docker_adapter_only_accepts_fixed_resource_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_container(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=f"Error response from daemon: No such container: {CONTAINER_NAME}",
        )

    monkeypatch.setattr("targets.docker_adapter.subprocess.run", missing_container)
    assert DockerAdapter().container() is None

    def daemon_failure(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="Cannot connect to Docker daemon")

    monkeypatch.setattr("targets.docker_adapter.subprocess.run", daemon_failure)
    with pytest.raises(DockerCommandError, match="inspection did not complete"):
        DockerAdapter().container()


def test_runtime_code_has_no_build_pull_or_compose_invocation() -> None:
    runtime_sources = "\n".join(
        (ROOT / "targets" / name).read_text(encoding="utf-8")
        for name in ("docker_adapter.py", "runtime.py")
    )
    assert '"build"' not in runtime_sources
    assert '"pull"' not in runtime_sources
    assert '"compose"' not in runtime_sources
