"""Fixed Docker command boundary for Crack's one approved local runtime."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


_ROOT: Final = Path(__file__).resolve().parents[1]
_DOCKER: Final = "docker"
PROJECT_NAME: Final = "crack-approved-school-portal"
NETWORK_NAME: Final = "crack-approved-school-portal-net"
CONTAINER_NAME: Final = "crack-approved-school-portal-app"
IMAGE_NAME: Final = "crack-approved-school-portal-runtime:v1"
TARGET_ID: Final = "crack-school-portal"
LABEL_RUNTIME: Final = "io.crack.runtime"
LABEL_PROJECT: Final = "io.crack.project"
LABEL_TARGET_ID: Final = "io.crack.target-id"
LABEL_SNAPSHOT_SHA256: Final = "io.crack.snapshot-sha256"
LABEL_DOCKERFILE_SHA256: Final = "io.crack.dockerfile-sha256"
_RUNTIME_LABEL_VALUE: Final = "sprint-17"
_COMMAND_TIMEOUT_SECONDS: Final = 30
_MAX_OUTPUT_CHARACTERS: Final = 4096
_SANITIZED_ENVIRONMENT: Final = {
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
}
_REDACT_ASSIGNMENT: Final = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?key|authorization|credential|password|secret|token)"
    r"\s*(?:=|:)\s*[^\s,;]+"
)
_REDACT_BEARER: Final = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_STATE_FINGERPRINT: Final = re.compile(r"^[0-9a-f]{16}$")
_STATE_FINGERPRINT_PROGRAM: Final = (
    "import hashlib,json,sqlite3;"
    "c=sqlite3.connect('/workspace/data/demo_app.db');"
    "q=lambda s:c.execute(s).fetchall();"
    "v={'people':q('SELECT id,role,token,display_name FROM people ORDER BY id'),"
    "'classes':q('SELECT id,teacher_id,title FROM classes ORDER BY id'),"
    "'assignments':q('SELECT id,class_id,title FROM assignments ORDER BY id'),"
    "'submissions':q('SELECT id,assignment_id,student_id,body FROM submissions ORDER BY id'),"
    "'grades':q('SELECT id,submission_id,teacher_id,feedback,state FROM grades ORDER BY id')};"
    "print(hashlib.sha256(json.dumps(v,separators=(',',':'),sort_keys=True).encode()).hexdigest()[:16])"
)


class DockerCommandError(RuntimeError):
    """Raised without exposing Docker, image, or target output."""


@dataclass(frozen=True)
class DockerCommandResult:
    """Bounded redacted command output retained only for fixed JSON parsing."""

    stdout: str
    stderr: str
    returncode: int


class DockerAdapter:
    """Run only fixed Docker argv vectors; never build, pull, or use Compose."""

    def image(self) -> dict[str, Any] | None:
        return self._inspect_object(("image", "inspect", "--format", "{{json .}}", IMAGE_NAME))

    def container(self) -> dict[str, Any] | None:
        return self._inspect_object(("container", "inspect", "--format", "{{json .}}", CONTAINER_NAME))

    def network(self) -> dict[str, Any] | None:
        return self._inspect_object(("network", "inspect", "--format", "{{json .}}", NETWORK_NAME))

    def create_network(self, snapshot_sha256: str, dockerfile_sha256: str) -> None:
        self._require_success(
            (
                "network", "create", "--driver", "bridge", "--internal",
                "--label", f"{LABEL_RUNTIME}={_RUNTIME_LABEL_VALUE}",
                "--label", f"{LABEL_PROJECT}={PROJECT_NAME}",
                "--label", f"{LABEL_TARGET_ID}={TARGET_ID}",
                "--label", f"{LABEL_SNAPSHOT_SHA256}={snapshot_sha256}",
                "--label", f"{LABEL_DOCKERFILE_SHA256}={dockerfile_sha256}",
                NETWORK_NAME,
            )
        )

    def run_container(self, image_id: str, snapshot_sha256: str, dockerfile_sha256: str) -> None:
        self._require_success(
            (
                "run", "--pull=never", "--detach", "--name", CONTAINER_NAME,
                "--label", f"{LABEL_RUNTIME}={_RUNTIME_LABEL_VALUE}",
                "--label", f"{LABEL_PROJECT}={PROJECT_NAME}",
                "--label", f"{LABEL_TARGET_ID}={TARGET_ID}",
                "--label", f"{LABEL_SNAPSHOT_SHA256}={snapshot_sha256}",
                "--label", f"{LABEL_DOCKERFILE_SHA256}={dockerfile_sha256}",
                "--network", NETWORK_NAME,
                "--publish", "127.0.0.1:8100:8100",
                "--read-only",
                "--tmpfs", "/workspace/data:rw,noexec,nosuid,mode=1777,size=16m",
                "--security-opt", "no-new-privileges:true",
                "--cap-drop", "ALL",
                "--pids-limit", "128",
                "--memory", "256m",
                "--cpus", "1.0",
                "--restart", "no",
                "--user", "65534:65534",
                "--env", "APP_DB_PATH=/workspace/data/demo_app.db",
                image_id,
            )
        )

    def seed_disposable_data(self) -> None:
        self._require_success(("exec", CONTAINER_NAME, "python", "-m", "scripts.seed"))

    def seeded_state_fingerprint(self) -> str:
        """Return only the fixed logical-state digest from the managed container."""
        result = self._invoke(
            (_DOCKER, "exec", CONTAINER_NAME, "python", "-c", _STATE_FINGERPRINT_PROGRAM)
        )
        if result.returncode != 0:
            raise DockerCommandError("fixed Docker state fingerprint did not complete")
        fingerprint = result.stdout.strip()
        if not _STATE_FINGERPRINT.fullmatch(fingerprint):
            raise DockerCommandError("fixed Docker state fingerprint was malformed")
        return fingerprint

    def remove_container(self) -> None:
        self._require_success(("container", "rm", "--force", CONTAINER_NAME))

    def remove_network(self) -> None:
        self._require_success(("network", "rm", NETWORK_NAME))

    def _inspect_labels(self, arguments: tuple[str, ...]) -> dict[str, str] | None:
        value = self._inspect_json(arguments)
        if value is None:
            return None
        if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
            raise DockerCommandError("fixed Docker inspection was malformed")
        return value

    def _inspect_object(self, arguments: tuple[str, ...]) -> dict[str, Any] | None:
        value = self._inspect_json(arguments)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise DockerCommandError("fixed Docker inspection was malformed")
        return value

    def _inspect_json(self, arguments: tuple[str, ...]) -> Any | None:
        result = self._invoke((_DOCKER, *arguments))
        if result.returncode != 0:
            if _is_known_missing_resource(arguments, result.stderr):
                return None
            raise DockerCommandError("fixed Docker inspection did not complete")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise DockerCommandError("fixed Docker inspection was malformed") from error

    def _require_success(self, arguments: tuple[str, ...]) -> None:
        result = self._invoke((_DOCKER, *arguments))
        if result.returncode != 0:
            raise DockerCommandError(f"fixed Docker command failed with exit status {result.returncode}")

    @staticmethod
    def _invoke(arguments: tuple[str, ...]) -> DockerCommandResult:
        try:
            completed = subprocess.run(
                arguments, check=False, capture_output=True, cwd=str(_ROOT),
                env=dict(_SANITIZED_ENVIRONMENT), shell=False, text=True,
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DockerCommandError("fixed Docker command did not complete") from error
        return DockerCommandResult(
            stdout=_safe_output(completed.stdout), stderr=_safe_output(completed.stderr),
            returncode=completed.returncode,
        )


def required_labels(snapshot_sha256: str, dockerfile_sha256: str) -> dict[str, str]:
    """Return exact label bindings required on pre-existing image and resources."""
    return {
        LABEL_RUNTIME: _RUNTIME_LABEL_VALUE,
        LABEL_PROJECT: PROJECT_NAME,
        LABEL_TARGET_ID: TARGET_ID,
        LABEL_SNAPSHOT_SHA256: snapshot_sha256,
        LABEL_DOCKERFILE_SHA256: dockerfile_sha256,
    }


def _safe_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    value = value or ""
    value = _REDACT_ASSIGNMENT.sub("[redacted]", value)
    value = _REDACT_BEARER.sub("Bearer [redacted]", value)
    return value[:_MAX_OUTPUT_CHARACTERS]


def _is_known_missing_resource(arguments: tuple[str, ...], stderr: str) -> bool:
    """Treat only Docker's fixed-resource absence as an idempotent empty state."""
    lower_stderr = stderr.casefold()
    if arguments[:2] == ("image", "inspect"):
        return "no such image" in lower_stderr and IMAGE_NAME.casefold() in lower_stderr
    if arguments[:2] == ("container", "inspect"):
        return "no such container" in lower_stderr and CONTAINER_NAME.casefold() in lower_stderr
    if arguments[:2] == ("network", "inspect"):
        return "no such network" in lower_stderr and NETWORK_NAME.casefold() in lower_stderr
    return False
