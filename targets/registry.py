"""Hash-bound, atomic registration for previously inspected target trees."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .inspection import ImportPlan, PlannedFile, TargetImportError, _open_regular_file, inspect_target


_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_ROOT = _ROOT / "targets" / "registry"
_SNAPSHOTS_DIRECTORY = "snapshots"
_ACTIVE_METADATA_NAME = "active-target.json"
_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class Registration:
    """Safe, non-source-path result of an approved registration attempt."""

    snapshot_sha256: str
    target_id: str
    file_count: int
    total_bytes: int
    reused_snapshot: bool


def register_approved(
    source_root: str | Path,
    approved_sha256: str,
    *,
    registry_root: str | Path = DEFAULT_REGISTRY_ROOT,
) -> Registration:
    """Reinspect, copy, and atomically activate exactly the approved snapshot."""
    if not _is_sha256(approved_sha256):
        raise TargetImportError("approval hash must be a lowercase SHA-256 value")
    plan = inspect_target(source_root)
    if plan.snapshot_sha256 != approved_sha256:
        raise TargetImportError("source snapshot does not match approval hash")

    root = _validate_registry_root(registry_root)
    _reject_overlapping_source(plan.source_root, root)
    root = _prepare_registry_root(root)
    snapshots = _ensure_directory(root / _SNAPSHOTS_DIRECTORY)
    final_snapshot = snapshots / plan.snapshot_sha256
    reused_snapshot = _path_exists_without_following(final_snapshot)
    if reused_snapshot:
        _verify_snapshot(final_snapshot, plan)
    else:
        stage = _make_staging_directory(root)
        try:
            _copy_plan(plan, stage)
            _verify_snapshot(stage, plan)
            if inspect_target(plan.source_root).snapshot_sha256 != approved_sha256:
                raise TargetImportError("source changed before activation")
            os.replace(stage, final_snapshot)
        except Exception:
            _remove_tree_no_follow(stage)
            raise

    if inspect_target(plan.source_root).snapshot_sha256 != approved_sha256:
        raise TargetImportError("source changed before active state update")
    _write_active_metadata(root, plan)
    return Registration(
        snapshot_sha256=plan.snapshot_sha256,
        target_id=plan.manifest.target_id,
        file_count=plan.file_count,
        total_bytes=plan.total_bytes,
        reused_snapshot=reused_snapshot,
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _validate_registry_root(registry_root: str | Path) -> Path:
    root = Path(registry_root)
    if not root.is_absolute() or ".." in root.parts:
        raise TargetImportError("registry root must be an absolute non-traversing path")
    return root


def _prepare_registry_root(registry_root: Path) -> Path:
    root = registry_root
    return _ensure_directory(root)


def _ensure_directory(path: Path) -> Path:
    """Create or validate each parent through non-following directory descriptors."""
    if not path.is_absolute() or ".." in path.parts:
        raise TargetImportError("registry directory is not safe")
    descriptor = _open_absolute_directory_chain(path, create=True)
    try:
        path_stat = os.fstat(descriptor)
    except OSError as error:
        raise TargetImportError("registry directory cannot be prepared") from error
    finally:
        os.close(descriptor)
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        raise TargetImportError("registry directory is not safe")
    return path


def _path_exists_without_following(path: Path) -> bool:
    _validate_existing_parent_chain(path.parent)
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        raise TargetImportError("registry snapshot path is not safe")
    return True


def _reject_overlapping_source(source_root: Path, registry_root: Path) -> None:
    source = os.path.realpath(os.path.abspath(source_root))
    registry = os.path.realpath(os.path.abspath(registry_root))
    if os.path.commonpath((source, registry)) in {source, registry}:
        raise TargetImportError("source and registry paths may not overlap")


def _make_staging_directory(registry_root: Path) -> Path:
    stage = registry_root / f".staging-{uuid4().hex}"
    _validate_existing_parent_chain(registry_root)
    try:
        stage.mkdir(mode=0o700)
    except OSError as error:
        raise TargetImportError("registry staging directory cannot be created") from error
    return stage


def _copy_plan(plan: ImportPlan, stage: Path) -> None:
    for planned_file in plan.files:
        destination = stage.joinpath(*planned_file.relative_path.split("/"))
        _ensure_directory(destination.parent)
        _copy_regular_file(planned_file, destination)


def _copy_regular_file(planned_file: PlannedFile, destination: Path) -> None:
    source_descriptor = _open_planned_file(planned_file)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        destination_descriptor = os.open(destination, flags, 0o600)
    except OSError as error:
        os.close(source_descriptor)
        raise TargetImportError("registry snapshot file cannot be created") from error
    try:
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(source_descriptor, _CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
            os.write(destination_descriptor, chunk)
        if size != planned_file.size or digest.hexdigest() != planned_file.sha256:
            raise TargetImportError("source changed while being copied")
    finally:
        os.close(destination_descriptor)
        os.close(source_descriptor)


def _open_planned_file(planned_file: PlannedFile) -> int:
    root = planned_file.source_path
    for _ in planned_file.source_relative_path.split("/"):
        root = root.parent
    try:
        root_stat = os.lstat(root)
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise TargetImportError("source file cannot be copied safely")
        descriptor = _open_regular_file(root, root_stat, planned_file.source_relative_path)
        source_stat = os.fstat(descriptor)
    except OSError as error:
        raise TargetImportError("source file cannot be copied safely") from error
    if (
        not stat.S_ISREG(source_stat.st_mode)
        or source_stat.st_dev != planned_file.device
        or source_stat.st_ino != planned_file.inode
    ):
        os.close(descriptor)
        raise TargetImportError("source changed while being copied")
    return descriptor


def _verify_snapshot(snapshot_root: Path, plan: ImportPlan) -> None:
    try:
        snapshot_plan = inspect_target(snapshot_root)
    except TargetImportError as error:
        raise TargetImportError("registry snapshot is not a safe approved target") from error
    if (
        snapshot_plan.snapshot_sha256 != plan.snapshot_sha256
        or snapshot_plan.manifest != plan.manifest
        or snapshot_plan.file_count != plan.file_count
        or snapshot_plan.total_bytes != plan.total_bytes
    ):
        raise TargetImportError("registry snapshot does not match approved source")


def _write_active_metadata(registry_root: Path, plan: ImportPlan) -> None:
    metadata = {
        "schema_version": 1,
        "snapshot_sha256": plan.snapshot_sha256,
        "snapshot_directory": f"{_SNAPSHOTS_DIRECTORY}/{plan.snapshot_sha256}",
        **plan.manifest.as_metadata(),
    }
    encoded = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8")
    active_metadata = registry_root / _ACTIVE_METADATA_NAME
    _validate_existing_parent_chain(registry_root)
    try:
        active_stat = os.lstat(active_metadata)
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(active_stat.st_mode) or not stat.S_ISREG(active_stat.st_mode):
            raise TargetImportError("active target metadata path is not safe")
    temporary = registry_root / f".{_ACTIVE_METADATA_NAME}.{uuid4().hex}.tmp"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, active_metadata)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise TargetImportError("active target metadata cannot be written") from error


def _remove_tree_no_follow(path: Path) -> None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode):
        path.unlink(missing_ok=True)
        return
    with os.scandir(path) as entries:
        for entry in entries:
            child = Path(entry.path)
            child_stat = os.lstat(child)
            if stat.S_ISDIR(child_stat.st_mode) and not stat.S_ISLNK(child_stat.st_mode):
                _remove_tree_no_follow(child)
            else:
                child.unlink(missing_ok=True)
    path.rmdir()


def _validate_existing_parent_chain(path: Path) -> None:
    descriptor = _open_absolute_directory_chain(path, create=False)
    os.close(descriptor)


def _open_absolute_directory_chain(path: Path, *, create: bool) -> int:
    """Open every absolute directory component without following symlinks."""
    if not path.is_absolute() or ".." in path.parts:
        raise TargetImportError("registry directory is not safe")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path.anchor, flags)
    except OSError as error:
        raise TargetImportError("registry directory cannot be prepared") from error
    try:
        for component in path.parts[1:]:
            try:
                entry_stat = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    raise TargetImportError("registry directory is not safe") from None
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    entry_stat = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                except OSError as error:
                    raise TargetImportError("registry directory cannot be prepared") from error
            except OSError as error:
                raise TargetImportError("registry directory cannot be prepared") from error
            if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(entry_stat.st_mode):
                raise TargetImportError("registry directory is not safe")
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except OSError as error:
                raise TargetImportError("registry directory is not safe") from error
            current = os.fstat(child)
            if (
                not stat.S_ISDIR(current.st_mode)
                or current.st_dev != entry_stat.st_dev
                or current.st_ino != entry_stat.st_ino
            ):
                os.close(child)
                raise TargetImportError("registry directory changed during preparation")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise
