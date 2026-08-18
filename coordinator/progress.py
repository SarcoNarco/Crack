"""Small, failure-isolated presentation callback shared by the demo stages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol


class ProgressCallback(Protocol):
    def __call__(
        self,
        *,
        event_type: str,
        stage: str,
        state: str,
        headline: str,
        explanation: str,
        logical_role: str | None = None,
        metadata: Mapping[str, object] | None = None,
        reference: str | None = None,
    ) -> None: ...


def notify(
    callback: ProgressCallback | Callable[..., None] | None,
    *,
    event_type: str,
    stage: str,
    state: str,
    headline: str,
    explanation: str,
    logical_role: str | None = None,
    metadata: Mapping[str, object] | None = None,
    reference: str | None = None,
) -> None:
    """Publish optional presentation state without affecting security execution."""
    if callback is None:
        return
    try:
        callback(
            event_type=event_type,
            stage=stage,
            state=state,
            headline=headline,
            explanation=explanation,
            logical_role=logical_role,
            metadata=dict(metadata or {}),
            reference=reference,
        )
    except Exception:
        # The presentation channel is explicitly non-authoritative. The ledger,
        # bounded calls, deterministic predicates, and verdict must continue.
        return
