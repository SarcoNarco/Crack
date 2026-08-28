"""Validated, replayable presentation events for the local operations console."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from coordinator.demo import DemoDependencies, DemoResult, run_demo


_ROOT = Path(__file__).resolve().parents[1]
_OUTPUT_ROOT = _ROOT / "demo" / "output"
_DATABASE_PATH = _ROOT / "data" / "ledger.db"
_REPORT_ROOT = (_ROOT / "reports" / "output").resolve()
_SESSION_PATTERN = re.compile(r"demo:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_SECRET_VALUE = re.compile(r"(?i)(?:bearer\s+\S+|sk-[a-z0-9_-]{16,}|gsk_[a-z0-9]{16,}|AIza[a-z0-9_-]{16,})")
_TERMINAL_TYPES = frozenset({"session.completed", "session.failed"})
_MAX_EVENTS = 256

EVENT_TYPES = (
    "session.started",
    "preflight.started", "preflight.completed",
    "mapper.activated", "mapper.completed",
    "identity_reset.started", "identity_reset.completed",
    "identity.activated", "identity.student_b_discovery", "identity.student_a_retrieval",
    "hypothesis.created", "identity.completed",
    "verifier_a.activated", "verifier_a.reset_completed", "verifier_a.plan_validated",
    "verifier_a.call_recorded", "verifier_a.check_completed", "verifier_a.completed",
    "verifier_b.activated", "verifier_b.reset_completed", "verifier_b.plan_validated",
    "verifier_b.call_recorded", "verifier_b.check_completed", "verifier_b.completed",
    "consensus.started", "consensus.completed", "finding.recorded",
    "report.started", "report.generated",
    "session.completed", "session.failed",
)

_METADATA_FIELDS: dict[str, frozenset[str]] = {
    "session.started": frozenset({"mode"}),
    "preflight.completed": frozenset({"role_bindings"}),
    "mapper.completed": frozenset({"route_count"}),
    "identity_reset.completed": frozenset({"reset_id", "state_hash"}),
    "identity.student_b_discovery": frozenset({"status_code", "submission_id", "student"}),
    "identity.student_a_retrieval": frozenset({
        "status_code", "requested_submission_id", "returned_submission_id", "returned_student",
        "exact_submission_match",
    }),
    "hypothesis.created": frozenset({"hypothesis_id"}),
    "identity.completed": frozenset({"identity_run_id", "hypothesis_id"}),
    "verifier_a.reset_completed": frozenset({"reset_id", "state_hash"}),
    "verifier_b.reset_completed": frozenset({"reset_id", "state_hash"}),
    "verifier_a.plan_validated": frozenset({"step_count", "plan_sha256"}),
    "verifier_b.plan_validated": frozenset({"step_count", "plan_sha256"}),
    "verifier_a.call_recorded": frozenset({
        "step_index", "role", "method", "proposed_path", "resolved_path", "executed",
        "status_code", "body_sha256",
    }),
    "verifier_b.call_recorded": frozenset({
        "step_index", "role", "method", "proposed_path", "resolved_path", "executed",
        "status_code", "body_sha256",
    }),
    "verifier_a.check_completed": frozenset({"satisfied", "matching_step_indexes"}),
    "verifier_b.check_completed": frozenset({"satisfied", "matching_step_indexes"}),
    "verifier_a.completed": frozenset({"satisfied"}),
    "verifier_b.completed": frozenset({"satisfied"}),
    "consensus.started": frozenset({"check_1_satisfied", "check_2_satisfied"}),
    "consensus.completed": frozenset({"check_1_satisfied", "check_2_satisfied", "verdict"}),
    "finding.recorded": frozenset({"finding_id", "hypothesis_id"}),
    "report.started": frozenset({"verifier_run_id"}),
    "report.generated": frozenset({
        "markdown_sha256", "html_sha256", "report_url", "verifier_run_id",
    }),
    "session.completed": frozenset({"verdict", "verifier_run_id", "finding_id", "report_url"}),
    "session.failed": frozenset({"failed_stage", "error_code"}),
}


class ReplayError(RuntimeError):
    """Presentation data is missing, malformed, partial, or out of sequence."""


class ActiveRunError(RuntimeError):
    """The fixed console already has one active run."""


def validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or _SESSION_PATTERN.fullmatch(session_id) is None:
        raise ValueError("invalid demo session ID")
    return session_id


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_metadata(event_type: str, metadata: Mapping[str, object]) -> dict[str, object]:
    allowed = _METADATA_FIELDS.get(event_type, frozenset())
    if set(metadata) - allowed:
        raise ValueError(f"{event_type} metadata contains a disallowed field")
    cleaned: dict[str, object] = {}
    for key, value in metadata.items():
        if value is None or isinstance(value, (bool, int)):
            cleaned[key] = value
        elif isinstance(value, str):
            if len(value) > 500 or _SECRET_VALUE.search(value):
                raise ValueError(f"{event_type} metadata contains an unsafe value")
            cleaned[key] = value
        elif isinstance(value, list) and len(value) <= 12 and all(
            isinstance(item, (str, int, bool)) and not isinstance(item, float)
            for item in value
        ):
            if any(isinstance(item, str) and (len(item) > 500 or _SECRET_VALUE.search(item)) for item in value):
                raise ValueError(f"{event_type} metadata contains an unsafe list value")
            cleaned[key] = list(value)
        else:
            raise ValueError(f"{event_type} metadata must contain bounded scalar values")
    return cleaned


class PresentationEvent(BaseModel):
    """Exact browser-safe event contract; the ledger remains authoritative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    sequence: int = Field(ge=0)
    type: str
    timestamp: str
    stage: Literal[
        "session", "preflight", "mapper", "authorization", "verifier_a", "verifier_b",
        "consensus", "report",
    ]
    logical_role: Literal[
        "coordinator", "mapper", "identity", "verifier_a", "verifier_b",
        "ordinary_code", "reporter",
    ] | None = None
    state: Literal["pending", "active", "completed", "failed", "blocked"]
    headline: str = Field(min_length=1, max_length=140)
    explanation: str = Field(min_length=1, max_length=600)
    metadata: dict[str, object] = Field(default_factory=dict)
    reference: str | None = Field(default=None, max_length=500)

    @field_validator("session_id")
    @classmethod
    def session_is_contained(cls, value: str) -> str:
        return validate_session_id(value)

    @field_validator("type")
    @classmethod
    def type_is_stable(cls, value: str) -> str:
        if value not in EVENT_TYPES:
            raise ValueError("unknown presentation event type")
        return value

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_utc(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise ValueError("timestamp must be UTC")
        return value

    @field_validator("headline", "explanation")
    @classmethod
    def prose_is_safe(cls, value: str) -> str:
        if _SECRET_VALUE.search(value) or any(character in value for character in ("\x00", "\r")):
            raise ValueError("presentation prose contains unsafe content")
        return value

    @field_validator("reference")
    @classmethod
    def reference_is_capability_free(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(("ledger://", "scope-controller://", "verifier://", "demo://", "report://")):
            raise ValueError("presentation reference uses a disallowed scheme")
        if _SECRET_VALUE.search(value) or ".." in value or "\\" in value:
            raise ValueError("presentation reference is unsafe")
        return value


class EventJournal:
    """Append-only, bounded JSONL journal with strict replay validation."""

    def __init__(self, output_root: Path, session_id: str, *, create: bool = False) -> None:
        self.session_id = validate_session_id(session_id)
        root = output_root.resolve()
        session_dir = (root / self.session_id).resolve()
        if session_dir.parent != root:
            raise ValueError("session path escaped the fixed output root")
        if create:
            session_dir.mkdir(parents=True, exist_ok=False)
        self.path = session_dir / "events.jsonl"
        self._lock = threading.Lock()

    def replay(self, *, after_sequence: int = -1) -> tuple[PresentationEvent, ...]:
        if not self.path.is_file():
            raise ReplayError("presentation event journal does not exist")
        raw = self.path.read_text(encoding="utf-8")
        if not raw or not raw.endswith("\n"):
            raise ReplayError("presentation event journal is empty or partial")
        events: list[PresentationEvent] = []
        for line_number, line in enumerate(raw.splitlines(), start=1):
            try:
                event = PresentationEvent.model_validate_json(line)
            except (ValidationError, ValueError) as exc:
                raise ReplayError(f"presentation event journal is malformed at line {line_number}") from exc
            if event.session_id != self.session_id or event.sequence != len(events):
                raise ReplayError("presentation event journal is out of sequence")
            if _safe_metadata(event.type, event.metadata) != event.metadata:
                raise ReplayError("presentation event metadata is not canonical")
            events.append(event)
        if len(events) > _MAX_EVENTS:
            raise ReplayError("presentation event journal exceeds its fixed event bound")
        return tuple(event for event in events if event.sequence > after_sequence)

    def publish(self, **update: object) -> PresentationEvent:
        with self._lock:
            existing = self.replay() if self.path.exists() else ()
            if existing and existing[-1].type in _TERMINAL_TYPES:
                raise RuntimeError("cannot append after a terminal presentation event")
            if len(existing) >= _MAX_EVENTS:
                raise RuntimeError("presentation event journal reached its fixed event bound")
            event_type = str(update.get("event_type", ""))
            metadata = _safe_metadata(event_type, update.get("metadata", {}))  # type: ignore[arg-type]
            event = PresentationEvent(
                session_id=self.session_id,
                sequence=len(existing),
                type=event_type,
                timestamp=_utc_now(),
                stage=update.get("stage"),
                logical_role=update.get("logical_role"),
                state=update.get("state"),
                headline=update.get("headline"),
                explanation=update.get("explanation"),
                metadata=metadata,
                reference=update.get("reference"),
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(event.model_dump_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return event


class LiveRunManager:
    """Own one fixed canonical run and its non-authoritative presentation journal."""

    def __init__(
        self,
        *,
        output_root: Path = _OUTPUT_ROOT,
        database_path: Path = _DATABASE_PATH,
        dependencies_factory: Callable[[], DemoDependencies] = DemoDependencies,
        runner: Callable[..., DemoResult] = run_demo,
    ) -> None:
        self.output_root = output_root
        self.database_path = database_path
        self.dependencies_factory = dependencies_factory
        self.runner = runner
        self._active_session: str | None = None
        self._journals: dict[str, EventJournal] = {}
        self._lock = threading.Lock()

    @property
    def active_session(self) -> str | None:
        with self._lock:
            return self._active_session

    def start(self) -> str:
        with self._lock:
            if self._active_session is not None:
                raise ActiveRunError("one contained demo run is already active")
            session_id = f"demo:{uuid.uuid4()}"
            journal = EventJournal(self.output_root, session_id, create=True)
            journal.publish(
                event_type="session.started", stage="session", state="active",
                logical_role="coordinator", headline="Contained verification run accepted",
                explanation=(
                    "The server generated this session and accepted the fixed local synthetic "
                    "workflow. No target or provider options were accepted."
                ),
                metadata={"mode": "live"},
            )
            self._journals[session_id] = journal
            self._active_session = session_id
        threading.Thread(
            target=self._execute,
            args=(session_id, journal),
            name="crack-contained-demo-runner",
            daemon=True,
        ).start()
        return session_id

    def _execute(self, session_id: str, journal: EventJournal) -> None:
        try:
            self.runner(
                dependencies=self.dependencies_factory(),
                output_root=self.output_root,
                database_path=self.database_path,
                emit=lambda _text: None,
                progress=journal.publish,
                session_id=session_id,
            )
        except Exception:
            try:
                current = journal.replay()
                if not current or current[-1].type not in _TERMINAL_TYPES:
                    stage = current[-1].stage if current else "session"
                    journal.publish(
                        event_type="session.failed", stage=stage, state="failed",
                        logical_role="coordinator", headline="Contained run stopped safely",
                        explanation=(
                            "The active stage failed, downstream stages were not activated, and "
                            "no verdict or finding was invented."
                        ),
                        metadata={"failed_stage": stage, "error_code": "stage_execution_failed"},
                    )
            except Exception:
                pass
        finally:
            with self._lock:
                if self._active_session == session_id:
                    self._active_session = None

    def journal(self, session_id: str) -> EventJournal:
        session_id = validate_session_id(session_id)
        journal = self._journals.get(session_id)
        if journal is not None:
            return journal
        journal = EventJournal(self.output_root, session_id)
        journal.replay()
        self._journals[session_id] = journal
        return journal

    def status(self, session_id: str) -> dict[str, object]:
        events = self.journal(session_id).replay()
        latest = events[-1]
        return {
            "session_id": session_id,
            "state": latest.state,
            "stage": latest.stage,
            "last_sequence": latest.sequence,
            "terminal": latest.type in _TERMINAL_TYPES,
            "events_url": f"/api/demo-runs/{session_id}/events",
        }

    def report_path(self, session_id: str) -> Path:
        session_id = validate_session_id(session_id)
        events = self.journal(session_id).replay()
        if not any(event.type == "report.generated" for event in events):
            raise ReplayError("report has not been generated for this session")
        manifest = self.output_root / session_id / "manifest.json"
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            html_path = Path(payload["html_path"]).resolve()
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ReplayError("session manifest cannot resolve the generated report") from exc
        if html_path.parent != _REPORT_ROOT or not html_path.is_file():
            raise ReplayError("generated report path is outside the fixed report output")
        return html_path
