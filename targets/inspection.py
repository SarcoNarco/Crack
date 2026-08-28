"""Read-only, non-following validation and deterministic hashing of target trees."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable

from .manifest import FIXED_COMPOSE_SHA256, MANIFEST_NAME, ManifestValidationError, TargetManifest


MAX_FILES: Final = 512
MAX_TOTAL_BYTES: Final = 16 * 1024 * 1024
MAX_FILE_BYTES: Final = 2 * 1024 * 1024
_CHUNK_SIZE: Final = 64 * 1024
_EXCLUDED_DIRECTORY_NAMES: Final = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "coverage",
        "data",
        "dist",
        "node_modules",
    }
)
_DATABASE_SUFFIXES: Final = (".db", ".sqlite", ".sqlite3", ".mdb")
_PRIVATE_KEY_NAMES: Final = frozenset({"id_dsa", "id_ecdsa", "id_ed25519", "id_rsa"})
_PRIVATE_KEY_SUFFIXES: Final = (".key", ".pem", ".p12", ".pfx")
_CREDENTIAL_FILE_NAMES: Final = frozenset(
    {
        "auth.json",
        "credential.json",
        "credential.yaml",
        "credential.yml",
        "credentials",
        "credentials.json",
        "credentials.yaml",
        "credentials.yml",
        "secret.json",
        "secrets.json",
        "service-account.json",
        "service_account.json",
        "token.json",
        "tokens.json",
    }
)
_SECRET_ASSIGNMENT: Final = re.compile(
    rb"(?im)^\s*(?:export\s+)?(?:[a-z_][a-z0-9_-]*?)?"
    rb"(?:secret|password|api[_-]?key|access[_-]?key|private[_-]?key|credential)"
    rb"[a-z0-9_-]*\s*=\s*(?:\"[^\"\r\n]+\"|'[^'\r\n]+'|[^\s#\r\n]+)"
)
_SECRET_JSON_VALUE: Final = re.compile(
    rb"(?i)\"(?:secret|token|password|api[_-]?key|access[_-]?key|private[_-]?key|credential)"
    rb"[a-z0-9_-]*\"\s*:\s*\"[^\"\r\n]+\""
)
_PRIVATE_KEY_CONTENT: Final = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_OBVIOUS_TOKEN_CONTENT: Final = re.compile(
    rb"(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
)


class TargetImportError(ValueError):
    """Safe failure message for invalid source trees or approval state."""


@dataclass(frozen=True)
class ImportLimits:
    """Fixed caps, injectable only by tests that use temporary source roots."""

    max_files: int = MAX_FILES
    max_total_bytes: int = MAX_TOTAL_BYTES
    max_file_bytes: int = MAX_FILE_BYTES


@dataclass(frozen=True)
class PlannedFile:
    """One regular source file that is safe to copy after approval."""

    relative_path: str
    source_path: Path
    size: int
    sha256: str
    device: int
    inode: int


@dataclass(frozen=True)
class ImportPlan:
    """Read-only snapshot plan; no source path is persisted to registry state."""

    source_root: Path
    manifest: TargetManifest
    files: tuple[PlannedFile, ...]
    total_bytes: int
    snapshot_sha256: str

    @property
    def file_count(self) -> int:
        return len(self.files)


def inspect_target(source_root: str | Path, *, limits: ImportLimits = ImportLimits()) -> ImportPlan:
    """Validate a local source tree and calculate its exact content snapshot hash."""
    root = _validate_source_root(source_root)
    candidates = list(_walk_regular_files(root, limits))
    relative_paths = [candidate[0] for candidate in candidates]
    if MANIFEST_NAME not in relative_paths:
        raise TargetImportError("target manifest is missing")
    if "docker-compose.yml" not in relative_paths:
        raise TargetImportError("fixed compose descriptor is missing")

    planned_files: list[PlannedFile] = []
    total_bytes = 0
    aggregate = hashlib.sha256()
    for relative_path, source_path, source_stat in candidates:
        if _is_secret_bearing_name(relative_path):
            raise TargetImportError("secret-bearing or database file is not allowed")
        if source_stat.st_size > limits.max_file_bytes:
            raise TargetImportError("per-file byte cap exceeded")
        if total_bytes + source_stat.st_size > limits.max_total_bytes:
            raise TargetImportError("total byte cap exceeded")
        aggregate.update(relative_path.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(source_stat.st_size.to_bytes(8, "big"))
        size, content_hash = _read_and_hash(source_path, source_stat, aggregate)
        total_bytes += size
        _reject_credential_like_content(source_path, content_hash, source_stat)
        planned_files.append(
            PlannedFile(
                relative_path=relative_path,
                source_path=source_path,
                size=size,
                sha256=content_hash,
                device=source_stat.st_dev,
                inode=source_stat.st_ino,
            )
        )

    planned_by_path = {file.relative_path: file for file in planned_files}
    try:
        manifest = TargetManifest.from_json_bytes(_read_planned_bytes(planned_by_path[MANIFEST_NAME]))
    except ManifestValidationError as error:
        raise TargetImportError(str(error)) from error
    compose_hash = planned_by_path[manifest.compose_file].sha256
    if compose_hash != FIXED_COMPOSE_SHA256:
        raise TargetImportError("compose descriptor is not the fixed supported shape")
    return ImportPlan(
        source_root=root,
        manifest=manifest,
        files=tuple(planned_files),
        total_bytes=total_bytes,
        snapshot_sha256=aggregate.hexdigest(),
    )


def _validate_source_root(source_root: str | Path) -> Path:
    root = Path(source_root)
    if not root.is_absolute() or ".." in root.parts:
        raise TargetImportError("source directory must be an absolute non-traversing path")
    try:
        root_stat = os.lstat(root)
    except OSError as error:
        raise TargetImportError("source directory is unavailable") from error
    if stat.S_ISLNK(root_stat.st_mode):
        raise TargetImportError("source directory may not be a symlink")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise TargetImportError("source path is not a directory")
    return root


def _walk_regular_files(root: Path, limits: ImportLimits) -> Iterable[tuple[str, Path, os.stat_result]]:
    seen_normalized: set[str] = set()
    files: list[tuple[str, Path, os.stat_result]] = []

    def walk(directory: Path, relative_directory: str) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: _normalized_component(entry.name))
        except OSError as error:
            raise TargetImportError("source directory cannot be inspected") from error
        for entry in entries:
            normalized_name = _normalized_component(entry.name)
            if not normalized_name or normalized_name in {".", ".."}:
                raise TargetImportError("source contains an invalid path")
            relative_path = normalized_name if not relative_directory else f"{relative_directory}/{normalized_name}"
            collision_key = relative_path.casefold()
            if collision_key in seen_normalized:
                raise TargetImportError("source contains ambiguous normalized paths")
            seen_normalized.add(collision_key)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise TargetImportError("source contains an unreadable path") from error
            if stat.S_ISLNK(entry_stat.st_mode):
                raise TargetImportError("source contains a symlink")
            if stat.S_ISDIR(entry_stat.st_mode):
                if entry.name in _EXCLUDED_DIRECTORY_NAMES:
                    continue
                walk(Path(entry.path), relative_path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise TargetImportError("source contains a non-regular file")
            files.append((relative_path, Path(entry.path), entry_stat))
            if len(files) > limits.max_files:
                raise TargetImportError("file cap exceeded")

    walk(root, "")
    yield from sorted(files, key=lambda item: item[0])


def _normalized_component(component: str) -> str:
    return unicodedata.normalize("NFC", component)


def _is_secret_bearing_name(relative_path: str) -> bool:
    name = relative_path.rsplit("/", 1)[-1].casefold()
    if name == ".env" or name.startswith(".env.") or name.startswith(".env_"):
        return True
    if name in _PRIVATE_KEY_NAMES or name.endswith(_PRIVATE_KEY_SUFFIXES):
        return True
    if name in _CREDENTIAL_FILE_NAMES or name.endswith(_DATABASE_SUFFIXES):
        return True
    return False


def _read_and_hash(
    path: Path, expected_stat: os.stat_result, aggregate: hashlib._Hash
) -> tuple[int, str]:
    descriptor = _open_regular_file(path)
    try:
        current_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(current_stat.st_mode)
            or current_stat.st_dev != expected_stat.st_dev
            or current_stat.st_ino != expected_stat.st_ino
        ):
            raise TargetImportError("source changed during inspection")
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, _CHUNK_SIZE):
            digest.update(chunk)
            aggregate.update(chunk)
            size += len(chunk)
        final_stat = os.fstat(descriptor)
        if final_stat.st_size != expected_stat.st_size or size != expected_stat.st_size:
            raise TargetImportError("source changed during inspection")
        return size, digest.hexdigest()
    finally:
        os.close(descriptor)


def _reject_credential_like_content(path: Path, digest: str, expected_stat: os.stat_result) -> None:
    del digest
    descriptor = _open_regular_file(path)
    try:
        current_stat = os.fstat(descriptor)
        if current_stat.st_dev != expected_stat.st_dev or current_stat.st_ino != expected_stat.st_ino:
            raise TargetImportError("source changed during inspection")
        content = bytearray()
        while chunk := os.read(descriptor, _CHUNK_SIZE):
            content.extend(chunk)
        if len(content) != expected_stat.st_size:
            raise TargetImportError("source changed during inspection")
    finally:
        os.close(descriptor)
    if (
        _SECRET_ASSIGNMENT.search(content)
        or _SECRET_JSON_VALUE.search(content)
        or _PRIVATE_KEY_CONTENT.search(content)
        or _OBVIOUS_TOKEN_CONTENT.search(content)
    ):
        raise TargetImportError("credential-like file content is not allowed")


def _read_planned_bytes(planned_file: PlannedFile) -> bytes:
    descriptor = _open_regular_file(planned_file.source_path)
    try:
        current_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(current_stat.st_mode)
            or current_stat.st_dev != planned_file.device
            or current_stat.st_ino != planned_file.inode
        ):
            raise TargetImportError("source changed during inspection")
        content = bytearray()
        while chunk := os.read(descriptor, _CHUNK_SIZE):
            content.extend(chunk)
        if len(content) != planned_file.size or hashlib.sha256(content).hexdigest() != planned_file.sha256:
            raise TargetImportError("source changed during inspection")
        return bytes(content)
    finally:
        os.close(descriptor)


def _open_regular_file(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(path, flags)
    except OSError as error:
        raise TargetImportError("source file cannot be read safely") from error
