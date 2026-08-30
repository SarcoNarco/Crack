"""Read-only validation for Crack's one active approved target snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .inspection import ImportPlan, PlannedFile, TargetImportError, inspect_target
from .registry import DEFAULT_REGISTRY_ROOT, _open_absolute_directory_chain


_SNAPSHOTS_DIRECTORY: Final = "snapshots"
_ACTIVE_METADATA_NAME: Final = "active-target.json"
_ACTIVE_SCHEMA_VERSION: Final = 1
_FIXED_TARGET_ID: Final = "crack-school-portal"
_FIXED_SERVICE: Final = "app-under-test"
_FIXED_PORT: Final = 8100
_FIXED_HEALTH_PATH: Final = "/health"
_FIXED_RESET_PROFILE: Final = "school-portal-v1"
_CHUNK_SIZE: Final = 64 * 1024


class ActiveTargetError(TargetImportError):
    """Safe failure for absent, malformed, or changed active registry state."""


@dataclass(frozen=True)
class _Identity:
    device: int
    inode: int


@dataclass(frozen=True)
class _ActiveState:
    registry_root: Path
    snapshot_sha256: str
    registry_identity: _Identity
    metadata_identity: _Identity
    metadata_bytes: bytes
    snapshots_identity: _Identity
    snapshot_identity: _Identity


@dataclass(frozen=True)
class ActiveTarget:
    """A revalidated active approved snapshot with no source-folder reference."""

    snapshot_root: Path
    plan: ImportPlan
    _state: _ActiveState


def load_active_target(
    registry_root: str | Path = DEFAULT_REGISTRY_ROOT,
) -> ActiveTarget:
    """Revalidate only the fixed active target metadata and approved snapshot."""
    state, metadata = _capture_active_state(Path(registry_root))
    snapshot_sha256 = metadata["snapshot_sha256"]
    snapshot_root = state.registry_root / _SNAPSHOTS_DIRECTORY / snapshot_sha256
    try:
        plan = inspect_target(snapshot_root)
    except TargetImportError as error:
        raise ActiveTargetError("active approved snapshot is unsafe or malformed") from error
    _assert_unchanged_state(state)
    if plan.snapshot_sha256 != snapshot_sha256:
        raise ActiveTargetError("active approved snapshot hash changed")
    if metadata["snapshot_directory"] != f"{_SNAPSHOTS_DIRECTORY}/{snapshot_sha256}":
        raise ActiveTargetError("active target metadata is mismatched")
    if metadata != _expected_metadata(plan):
        raise ActiveTargetError("active target metadata is mismatched")
    return ActiveTarget(snapshot_root=snapshot_root, plan=plan, _state=state)


def read_active_file(active: ActiveTarget, relative_path: str) -> bytes:
    """Read one previously inspected snapshot file without following paths."""
    planned = next((item for item in active.plan.files if item.relative_path == relative_path), None)
    if planned is None:
        raise ActiveTargetError("approved snapshot source is missing")
    _assert_unchanged_state(active._state)
    try:
        content = _read_planned_file(active._state, planned)
    except ActiveTargetError:
        raise
    except OSError as error:
        raise ActiveTargetError("approved snapshot source is unavailable") from error
    _assert_unchanged_state(active._state)
    return content


def _capture_active_state(registry_root: Path) -> tuple[_ActiveState, dict[str, object]]:
    root_fd = _open_registry_root(registry_root)
    try:
        registry_identity = _identity(os.fstat(root_fd))
        metadata_bytes, metadata_identity = _read_regular_file_at(
            root_fd, _ACTIVE_METADATA_NAME, "active target metadata"
        )
        metadata = _parse_active_metadata(metadata_bytes)
        snapshots_fd, snapshots_identity = _open_child_directory(
            root_fd, _SNAPSHOTS_DIRECTORY, "target snapshots"
        )
        try:
            snapshot_fd, snapshot_identity = _open_child_directory(
                snapshots_fd,
                metadata["snapshot_sha256"],
                "approved target snapshot",
            )
            os.close(snapshot_fd)
        finally:
            os.close(snapshots_fd)
    finally:
        os.close(root_fd)
    return (
        _ActiveState(
            registry_root=registry_root,
            snapshot_sha256=metadata["snapshot_sha256"],
            registry_identity=registry_identity,
            metadata_identity=metadata_identity,
            metadata_bytes=metadata_bytes,
            snapshots_identity=snapshots_identity,
            snapshot_identity=snapshot_identity,
        ),
        metadata,
    )


def _assert_unchanged_state(expected: _ActiveState) -> None:
    try:
        current, _ = _capture_active_state(expected.registry_root)
    except ActiveTargetError as error:
        raise ActiveTargetError("active approved target changed during validation") from error
    if current != expected:
        raise ActiveTargetError("active approved target changed during validation")


def _open_registry_root(registry_root: Path) -> int:
    try:
        return _open_absolute_directory_chain(registry_root, create=False)
    except TargetImportError as error:
        raise ActiveTargetError("target registry is unsafe") from error


def _open_child_directory(parent_fd: int, name: str, description: str) -> tuple[int, _Identity]:
    try:
        expected = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as error:
        raise ActiveTargetError(f"{description} is unavailable") from error
    except OSError as error:
        raise ActiveTargetError(f"{description} cannot be inspected safely") from error
    if stat.S_ISLNK(expected.st_mode) or not stat.S_ISDIR(expected.st_mode):
        raise ActiveTargetError(f"{description} is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise ActiveTargetError(f"{description} cannot be inspected safely") from error
    current = os.fstat(descriptor)
    if not stat.S_ISDIR(current.st_mode) or _identity(current) != _identity(expected):
        os.close(descriptor)
        raise ActiveTargetError(f"{description} changed during validation")
    return descriptor, _identity(current)


def _read_regular_file_at(parent_fd: int, name: str, description: str) -> tuple[bytes, _Identity]:
    try:
        expected = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as error:
        raise ActiveTargetError(f"{description} is unavailable") from error
    except OSError as error:
        raise ActiveTargetError(f"{description} cannot be inspected safely") from error
    if stat.S_ISLNK(expected.st_mode) or not stat.S_ISREG(expected.st_mode):
        raise ActiveTargetError(f"{description} is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise ActiveTargetError(f"{description} cannot be read safely") from error
    try:
        current = os.fstat(descriptor)
        if not stat.S_ISREG(current.st_mode) or _identity(current) != _identity(expected):
            raise ActiveTargetError(f"{description} changed during read")
        content = bytearray()
        while chunk := os.read(descriptor, _CHUNK_SIZE):
            content.extend(chunk)
        final = os.fstat(descriptor)
        if _identity(final) != _identity(current) or final.st_size != len(content):
            raise ActiveTargetError(f"{description} changed during read")
        return bytes(content), _identity(current)
    finally:
        os.close(descriptor)


def _read_planned_file(state: _ActiveState, planned: PlannedFile) -> bytes:
    snapshot_fd = _open_pinned_snapshot(state)
    descriptors = [snapshot_fd]
    try:
        parts = planned.source_relative_path.split("/")
        if not parts or any(not part or part in {".", ".."} for part in parts):
            raise ActiveTargetError("approved snapshot source is missing")
        directory_fd = snapshot_fd
        for component in parts[:-1]:
            child_fd, _ = _open_child_directory(
                directory_fd, component, "approved snapshot source directory"
            )
            descriptors.append(child_fd)
            directory_fd = child_fd
        content, identity = _read_regular_file_at(
            directory_fd, parts[-1], "approved snapshot source"
        )
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    if (
        identity != _Identity(planned.device, planned.inode)
        or len(content) != planned.size
        or hashlib.sha256(content).hexdigest() != planned.sha256
    ):
        raise ActiveTargetError("approved snapshot changed during source read")
    return content


def _open_pinned_snapshot(state: _ActiveState) -> int:
    root_fd = _open_registry_root(state.registry_root)
    try:
        if _identity(os.fstat(root_fd)) != state.registry_identity:
            raise ActiveTargetError("active approved target changed during validation")
        snapshots_fd, snapshots_identity = _open_child_directory(
            root_fd, _SNAPSHOTS_DIRECTORY, "target snapshots"
        )
        try:
            if snapshots_identity != state.snapshots_identity:
                raise ActiveTargetError("active approved target changed during validation")
            snapshot_fd, snapshot_identity = _open_child_directory(
                snapshots_fd, state.snapshot_sha256, "approved target snapshot"
            )
        finally:
            os.close(snapshots_fd)
        if snapshot_identity != state.snapshot_identity:
            os.close(snapshot_fd)
            raise ActiveTargetError("active approved target changed during validation")
        return snapshot_fd
    finally:
        os.close(root_fd)


def _identity(value: os.stat_result) -> _Identity:
    return _Identity(device=value.st_dev, inode=value.st_ino)


def _expected_metadata(plan: ImportPlan) -> dict[str, object]:
    return {
        "schema_version": _ACTIVE_SCHEMA_VERSION,
        "snapshot_sha256": plan.snapshot_sha256,
        "snapshot_directory": f"{_SNAPSHOTS_DIRECTORY}/{plan.snapshot_sha256}",
        **plan.manifest.as_metadata(),
    }


def _parse_active_metadata(content: bytes) -> dict[str, object]:
    try:
        raw = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ActiveTargetError("active target metadata is malformed") from error
    shape = _expected_metadata_shape()
    if not isinstance(raw, dict) or set(raw) != set(shape):
        raise ActiveTargetError("active target metadata is malformed")
    for key, expected_type in shape.items():
        if type(raw[key]) is not expected_type:
            raise ActiveTargetError("active target metadata is malformed")
    if (
        raw["schema_version"] != _ACTIVE_SCHEMA_VERSION
        or not _is_sha256(raw["snapshot_sha256"])
        or raw["target_id"] != _FIXED_TARGET_ID
        or raw["runtime"] != "docker-compose"
        or raw["service"] != _FIXED_SERVICE
        or raw["internal_port"] != _FIXED_PORT
        or raw["health_path"] != _FIXED_HEALTH_PATH
        or raw["reset_profile"] != _FIXED_RESET_PROFILE
    ):
        raise ActiveTargetError("active target metadata is malformed")
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


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
