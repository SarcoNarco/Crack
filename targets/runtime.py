"""Fail-closed runtime handoff for one approved Sprint 16 school-portal snapshot."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final

from .docker_adapter import (
    CONTAINER_NAME,
    DockerAdapter,
    DockerCommandError,
    NETWORK_NAME,
    TARGET_ID,
    required_labels,
)
from .inspection import ImportPlan, TargetImportError, inspect_target
from .registry import DEFAULT_REGISTRY_ROOT, _validate_existing_parent_chain


_SNAPSHOTS_DIRECTORY: Final = "snapshots"
_ACTIVE_METADATA_NAME: Final = "active-target.json"
_ACTIVE_SCHEMA_VERSION: Final = 1
_FIXED_SERVICE: Final = "app-under-test"
_FIXED_PORT: Final = 8100
_FIXED_HEALTH_PATH: Final = "/health"
_FIXED_RESET_PROFILE: Final = "school-portal-v1"
_FIXED_DOCKERFILE_PATH: Final = "Dockerfile"
_FIXED_DOCKERFILE_CONTENT: Final = (
    b"FROM python:3.12-slim\n"
    b"\n"
    b"WORKDIR /workspace\n"
    b"\n"
    b"COPY requirements.txt .\n"
    b"RUN pip install --no-cache-dir -r requirements.txt\n"
    b"\n"
    b"COPY app ./app\n"
    b"COPY scripts ./scripts\n"
    b"\n"
    b"EXPOSE 8100\n"
    b"\n"
    b"CMD [\"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8100\"]\n"
)
FIXED_DOCKERFILE_SHA256: Final = hashlib.sha256(_FIXED_DOCKERFILE_CONTENT).hexdigest()
_HEALTH_TIMEOUT_SECONDS: Final = 5
_HEALTH_POLL_SECONDS: Final = 0.1
_IMAGE_ID: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_DATABASE_ENVIRONMENT: Final = "APP_DB_PATH=/workspace/data/demo_app.db"
_FORBIDDEN_ENVIRONMENT_NAMES: Final = frozenset({"GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"})


class RuntimeHandoffError(TargetImportError):
    """Safe failure for missing, changed, or unusable approved runtime state."""


@dataclass(frozen=True)
class ActiveTarget:
    """Fully revalidated local registry state, without source-folder reference."""

    snapshot_root: Path
    plan: ImportPlan


@dataclass(frozen=True)
class RuntimeStatus:
    """Safe state returned by the fixed runtime boundary."""

    state: str
    snapshot_sha256: str
    target_id: str


@dataclass(frozen=True)
class _ImageContract:
    """Immutable image identity plus its exact inherited environment."""

    image_id: str
    environment: tuple[str, ...]


class RuntimeService:
    """Start, status, and stop only one label-bound local container."""

    def __init__(
        self,
        *,
        registry_root: str | Path = DEFAULT_REGISTRY_ROOT,
        docker: DockerAdapter | None = None,
        health_probe: Callable[[], None] | None = None,
    ) -> None:
        self._registry_root = Path(registry_root)
        self._docker = docker or DockerAdapter()
        self._health_probe = health_probe or _probe_loopback_health

    def start(self, approved_sha256: str) -> RuntimeStatus:
        return self._translate_docker_failure(lambda: self._start(approved_sha256))

    def _start(self, approved_sha256: str) -> RuntimeStatus:
        active = self._load_active_target()
        if not _is_sha256(approved_sha256) or approved_sha256 != active.plan.snapshot_sha256:
            raise RuntimeHandoffError("approval hash does not match the active approved snapshot")
        labels = required_labels(active.plan.snapshot_sha256, FIXED_DOCKERFILE_SHA256)
        image = _validated_image(self._docker.image(), labels)

        existing_container = self._docker.container()
        existing_network = self._docker.network()
        if existing_network is not None:
            _validate_network(existing_network, labels)
        if existing_container is not None:
            state = _validated_container_state(existing_container, labels, image)
            if state == "running":
                if existing_network is None:
                    raise RuntimeHandoffError("fixed runtime network is missing")
                self._health_probe()
                return _status("running", active)
            self._docker.remove_container()

        network_attempted = False
        container_attempted = False
        try:
            if existing_network is None:
                network_attempted = True
                self._docker.create_network(active.plan.snapshot_sha256, FIXED_DOCKERFILE_SHA256)
            if _validated_image(self._docker.image(), labels).image_id != image.image_id:
                raise RuntimeHandoffError("required local offline image changed before start")
            container_attempted = True
            self._docker.run_container(image.image_id, active.plan.snapshot_sha256, FIXED_DOCKERFILE_SHA256)
            created_container = self._docker.container()
            if created_container is None:
                raise RuntimeHandoffError("fixed runtime container was not created")
            _validated_container_state(created_container, labels, image)
            self._docker.seed_disposable_data()
            self._health_probe()
        except (DockerCommandError, RuntimeHandoffError, OSError, http.client.HTTPException) as error:
            complete = self._rollback(
                container_attempted=container_attempted,
                network_attempted=network_attempted,
                labels=labels,
                image=image,
            )
            message = (
                "fixed runtime start failed; rolled back new fixed resources"
                if complete
                else "fixed runtime start failed; rollback incomplete"
            )
            raise RuntimeHandoffError(message) from error
        return _status("started", active)

    def status(self) -> RuntimeStatus:
        return self._translate_docker_failure(self._status)

    def _status(self) -> RuntimeStatus:
        active = self._load_active_target()
        container = self._docker.container()
        network = self._docker.network()
        labels = required_labels(active.plan.snapshot_sha256, FIXED_DOCKERFILE_SHA256)
        if network is not None:
            _validate_network(network, labels)
        if container is None:
            return _status("stopped", active)
        if network is None:
            raise RuntimeHandoffError("fixed runtime network is missing")
        image = _validated_image(self._docker.image(), labels)
        return _status(_validated_container_state(container, labels, image), active)

    def stop(self) -> RuntimeStatus:
        return self._translate_docker_failure(self._stop)

    def _stop(self) -> RuntimeStatus:
        active = self._load_active_target()
        labels = required_labels(active.plan.snapshot_sha256, FIXED_DOCKERFILE_SHA256)
        container = self._docker.container()
        network = self._docker.network()
        if container is not None:
            image = _validated_image(self._docker.image(), labels)
            _validated_container_state(container, labels, image)
            self._docker.remove_container()
        if network is not None:
            _validate_network(network, labels)
            self._docker.remove_network()
        return _status("stopped", active)

    def _rollback(
        self, *, container_attempted: bool, network_attempted: bool, labels: dict[str, str], image: _ImageContract
    ) -> bool:
        complete = True
        if container_attempted:
            try:
                container = self._docker.container()
                if container is not None:
                    _validated_container_state(container, labels, image)
                    self._docker.remove_container()
            except (DockerCommandError, RuntimeHandoffError):
                complete = False
        if network_attempted:
            try:
                network = self._docker.network()
                if network is not None:
                    _validate_network(network, labels)
                    self._docker.remove_network()
            except (DockerCommandError, RuntimeHandoffError):
                complete = False
        return complete

    @staticmethod
    def _translate_docker_failure(operation: Callable[[], RuntimeStatus]) -> RuntimeStatus:
        try:
            return operation()
        except DockerCommandError as error:
            raise RuntimeHandoffError("fixed Docker runtime operation failed") from error

    def _load_active_target(self) -> ActiveTarget:
        registry_root = _require_directory(self._registry_root, "target registry")
        metadata = _read_active_metadata(registry_root)
        snapshot_sha256 = metadata["snapshot_sha256"]
        snapshots_root = _require_directory(registry_root / _SNAPSHOTS_DIRECTORY, "target snapshots")
        snapshot_root = _require_directory(snapshots_root / snapshot_sha256, "approved target snapshot")
        try:
            plan = inspect_target(snapshot_root)
        except TargetImportError as error:
            raise RuntimeHandoffError("active approved snapshot is unsafe or malformed") from error
        if plan.snapshot_sha256 != snapshot_sha256:
            raise RuntimeHandoffError("active approved snapshot hash changed")
        if metadata["snapshot_directory"] != f"{_SNAPSHOTS_DIRECTORY}/{snapshot_sha256}":
            raise RuntimeHandoffError("active target metadata is mismatched")
        if metadata != _expected_metadata(plan):
            raise RuntimeHandoffError("active target metadata is mismatched")
        _require_fixed_dockerfile(plan)
        return ActiveTarget(snapshot_root=snapshot_root, plan=plan)


def _status(state: str, active: ActiveTarget) -> RuntimeStatus:
    return RuntimeStatus(state=state, snapshot_sha256=active.plan.snapshot_sha256, target_id=active.plan.manifest.target_id)


def _expected_metadata(plan: ImportPlan) -> dict[str, object]:
    return {
        "schema_version": _ACTIVE_SCHEMA_VERSION,
        "snapshot_sha256": plan.snapshot_sha256,
        "snapshot_directory": f"{_SNAPSHOTS_DIRECTORY}/{plan.snapshot_sha256}",
        **plan.manifest.as_metadata(),
    }


def _read_active_metadata(registry_root: Path) -> dict[str, object]:
    content = _read_regular_file(registry_root / _ACTIVE_METADATA_NAME, "active target metadata")
    try:
        raw = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeHandoffError("active target metadata is malformed") from error
    shape = _expected_metadata_shape()
    if not isinstance(raw, dict) or set(raw) != set(shape):
        raise RuntimeHandoffError("active target metadata is malformed")
    for key, expected_type in shape.items():
        if type(raw[key]) is not expected_type:
            raise RuntimeHandoffError("active target metadata is malformed")
    if (
        raw["schema_version"] != _ACTIVE_SCHEMA_VERSION
        or not _is_sha256(raw["snapshot_sha256"])
        or raw["target_id"] != TARGET_ID
        or raw["runtime"] != "docker-compose"
        or raw["service"] != _FIXED_SERVICE
        or raw["internal_port"] != _FIXED_PORT
        or raw["health_path"] != _FIXED_HEALTH_PATH
        or raw["reset_profile"] != _FIXED_RESET_PROFILE
    ):
        raise RuntimeHandoffError("active target metadata is malformed")
    return raw


def _expected_metadata_shape() -> dict[str, type[object]]:
    return {
        "schema_version": int,
        "snapshot_sha256": str,
        "snapshot_directory": str,
        "target_id": str,
        "runtime": str,
        "service": str,
        "internal_port": int,
        "health_path": str,
        "reset_profile": str,
    }


def _require_fixed_dockerfile(plan: ImportPlan) -> None:
    dockerfile = next((item for item in plan.files if item.relative_path == _FIXED_DOCKERFILE_PATH), None)
    if dockerfile is None or dockerfile.sha256 != FIXED_DOCKERFILE_SHA256:
        raise RuntimeHandoffError("approved snapshot Dockerfile is not the fixed runtime contract")
    if _read_regular_file(dockerfile.source_path, "approved snapshot Dockerfile") != _FIXED_DOCKERFILE_CONTENT:
        raise RuntimeHandoffError("approved snapshot Dockerfile changed")


def _validated_image(image: dict[str, Any] | None, labels: dict[str, str]) -> _ImageContract:
    config = image.get("Config") if image is not None else None
    if not isinstance(config, dict) or config.get("Labels") != labels:
        raise RuntimeHandoffError("required local offline image is missing or not bound to approved snapshot")
    image_id = image.get("Id")
    if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
        raise RuntimeHandoffError("required local offline image has no valid immutable ID")
    environment = _valid_environment(config.get("Env"), "image")
    if _DATABASE_ENVIRONMENT in environment or _has_forbidden_environment(environment):
        raise RuntimeHandoffError("required local offline image has unsafe environment")
    return _ImageContract(image_id=image_id, environment=environment)


def _validated_container_state(
    container: dict[str, Any], labels: dict[str, str], image: _ImageContract
) -> str:
    config = container.get("Config")
    state = container.get("State")
    host = container.get("HostConfig")
    network_settings = container.get("NetworkSettings")
    if not all(isinstance(value, dict) for value in (config, state, host, network_settings)):
        raise RuntimeHandoffError("fixed runtime container inspection was malformed")
    if (
        config.get("Labels") != labels
        or container.get("Name") not in {CONTAINER_NAME, f"/{CONTAINER_NAME}"}
        or container.get("Image") != image.image_id
        or config.get("User") != "65534:65534"
    ):
        raise RuntimeHandoffError("refusing container with different approved hash or ownership")
    _validate_container_containment(container, config, host, network_settings, image.environment)
    value = state.get("Status")
    if value == "running":
        return "running"
    if value in {"created", "dead", "exited"}:
        return "stopped"
    raise RuntimeHandoffError("fixed runtime container inspection was malformed")


def _validate_network(network: dict[str, Any], labels: dict[str, str]) -> None:
    if (
        network.get("Name") != NETWORK_NAME
        or network.get("Labels") != labels
        or network.get("Driver") != "bridge"
        or network.get("Scope") != "local"
        or network.get("Internal") is not True
        or network.get("Attachable") is not False
        or network.get("Ingress") is not False
        or network.get("ConfigOnly") is not False
    ):
        raise RuntimeHandoffError("refusing network with different approved hash or containment")


def _validate_container_containment(
    container: dict[str, Any],
    config: dict[str, Any],
    host: dict[str, Any],
    network_settings: dict[str, Any],
    image_environment: tuple[str, ...],
) -> None:
    environment = _valid_environment(config.get("Env"), "container")
    if environment != (*image_environment, _DATABASE_ENVIRONMENT) or _has_forbidden_environment(environment):
        raise RuntimeHandoffError("refusing container with different approved hash or ownership")
    if config.get("Volumes") not in (None, {}):
        raise RuntimeHandoffError("refusing container with different approved hash or ownership")
    if (
        host.get("Privileged") is not False
        or host.get("CapAdd") not in (None, [])
        or host.get("CapDrop") != ["ALL"]
        or host.get("Devices") not in (None, [])
        or host.get("Binds") not in (None, [])
        or host.get("Mounts") not in (None, [])
        or host.get("DeviceRequests") not in (None, [])
        or host.get("NetworkMode") != NETWORK_NAME
        or host.get("ReadonlyRootfs") is not True
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
        or host.get("PidsLimit") != 128
        or host.get("Memory") != 256 * 1024 * 1024
        or host.get("NanoCpus") != 1_000_000_000
        or host.get("RestartPolicy") != {"Name": "no", "MaximumRetryCount": 0}
        or host.get("IpcMode") not in (None, "private")
        or host.get("PidMode") not in (None, "")
    ):
        raise RuntimeHandoffError("refusing container with different approved hash or containment")
    mounts = network_settings.get("Ports")
    if mounts != {"8100/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8100"}]}:
        raise RuntimeHandoffError("refusing container with different approved hash or containment")
    networks = network_settings.get("Networks")
    if not isinstance(networks, dict) or set(networks) != {NETWORK_NAME}:
        raise RuntimeHandoffError("refusing container with different approved hash or ownership")
    if host.get("Tmpfs") != {"/workspace/data": "rw,noexec,nosuid,mode=1777,size=16m"}:
        raise RuntimeHandoffError("refusing container with different approved hash or ownership")
    inspected_mounts = container.get("Mounts")
    if (
        not isinstance(inspected_mounts, list)
        or len(inspected_mounts) != 1
        or not isinstance(inspected_mounts[0], dict)
        or inspected_mounts[0].get("Type") != "tmpfs"
        or inspected_mounts[0].get("Destination") != "/workspace/data"
        or inspected_mounts[0].get("RW") is not True
        or inspected_mounts[0].get("Source") not in (None, "")
    ):
        raise RuntimeHandoffError("refusing container with different approved hash or ownership")


def _valid_environment(value: object, owner: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and "=" in item for item in value):
        raise RuntimeHandoffError(f"{owner} environment inspection was malformed")
    names = [item.partition("=")[0] for item in value]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise RuntimeHandoffError(f"{owner} environment inspection was malformed")
    return tuple(value)


def _has_forbidden_environment(environment: tuple[str, ...]) -> bool:
    return any(item.partition("=")[0] in _FORBIDDEN_ENVIRONMENT_NAMES for item in environment)


def _require_directory(path: Path, description: str) -> Path:
    try:
        _validate_existing_parent_chain(path)
    except TargetImportError as error:
        raise RuntimeHandoffError(f"{description} is unsafe") from error
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise RuntimeHandoffError(f"{description} is unavailable") from error
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        raise RuntimeHandoffError(f"{description} is unsafe")
    return path


def _read_regular_file(path: Path, description: str) -> bytes:
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise RuntimeHandoffError(f"{description} is unavailable") from error
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise RuntimeHandoffError(f"{description} is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RuntimeHandoffError(f"{description} cannot be read safely") from error
    try:
        current_stat = os.fstat(descriptor)
        if not stat.S_ISREG(current_stat.st_mode) or (current_stat.st_dev, current_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise RuntimeHandoffError(f"{description} changed during read")
        content = bytearray()
        while chunk := os.read(descriptor, 64 * 1024):
            content.extend(chunk)
        return bytes(content)
    finally:
        os.close(descriptor)


def _probe_loopback_health(
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    connection_factory: Callable[..., http.client.HTTPConnection] = http.client.HTTPConnection,
) -> None:
    deadline = clock() + _HEALTH_TIMEOUT_SECONDS
    while True:
        connection: http.client.HTTPConnection | None = None
        try:
            connection = connection_factory("127.0.0.1", _FIXED_PORT, timeout=_HEALTH_POLL_SECONDS)
            connection.request("GET", _FIXED_HEALTH_PATH)
            response = connection.getresponse()
            if response.status == 200 and response.read(4096) == b'{"status":"ok"}':
                return
        except (OSError, http.client.HTTPException):
            pass
        finally:
            if connection is not None:
                connection.close()
        remaining = deadline - clock()
        if remaining <= 0:
            raise RuntimeHandoffError("fixed runtime health check failed")
        sleep(min(_HEALTH_POLL_SECONDS, remaining))


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m targets.runtime", description="Control only Crack's active approved local target snapshot.")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="start exact snapshot from pre-existing local image")
    start.add_argument("--approve-sha256", required=True, help="exact active snapshot SHA-256")
    commands.add_parser("status", help="read fixed-project status after revalidation")
    commands.add_parser("stop", help="stop only fixed label-matched resources")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = RuntimeService()
    try:
        result = service.start(args.approve_sha256) if args.command == "start" else (service.status() if args.command == "status" else service.stop())
    except RuntimeHandoffError as error:
        print(f"error: {error}")
        return 2
    print(f"runtime={result.state}")
    print(f"target_id={result.target_id}")
    print(f"snapshot_sha256={result.snapshot_sha256}")
    print(f"health_path={_FIXED_HEALTH_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
