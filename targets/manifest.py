"""Strict, dependency-free manifest validation for the sole Sprint 16 target."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final


MANIFEST_NAME: Final = "crack-target.json"
FIXED_COMPOSE_CONTENT: Final = b"services:\n  app-under-test:\n    build: .\n    expose:\n      - \"8100\"\n"
FIXED_COMPOSE_SHA256: Final = hashlib.sha256(FIXED_COMPOSE_CONTENT).hexdigest()
_EXPECTED_MANIFEST: Final[dict[str, object]] = {
    "schema_version": 1,
    "target_id": "crack-school-portal",
    "runtime": "docker-compose",
    "compose_file": "docker-compose.yml",
    "service": "app-under-test",
    "internal_port": 8100,
    "health_path": "/health",
    "reset_profile": "school-portal-v1",
}


class ManifestValidationError(ValueError):
    """Raised when a target manifest is not the one fixed supported shape."""


@dataclass(frozen=True)
class TargetManifest:
    """The fully fixed local runtime declaration retained with a snapshot."""

    schema_version: int
    target_id: str
    runtime: str
    compose_file: str
    service: str
    internal_port: int
    health_path: str
    reset_profile: str

    @classmethod
    def from_json_bytes(cls, content: bytes) -> "TargetManifest":
        try:
            raw = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ManifestValidationError("target manifest is not valid JSON") from error
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: Any) -> "TargetManifest":
        if not isinstance(raw, dict):
            raise ManifestValidationError("target manifest must be a JSON object")

        expected_keys = set(_EXPECTED_MANIFEST)
        actual_keys = set(raw)
        if actual_keys != expected_keys:
            raise ManifestValidationError("target manifest fields are not exactly supported")

        for field, expected in _EXPECTED_MANIFEST.items():
            if raw[field] != expected or type(raw[field]) is not type(expected):
                raise ManifestValidationError(f"target manifest field {field!r} is not supported")

        return cls(**raw)

    def as_metadata(self) -> dict[str, object]:
        """Return non-secret fixed metadata for the active-target record."""
        return {
            "target_id": self.target_id,
            "runtime": self.runtime,
            "service": self.service,
            "internal_port": self.internal_port,
            "health_path": self.health_path,
            "reset_profile": self.reset_profile,
        }
