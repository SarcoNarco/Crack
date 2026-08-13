"""The complete public capability surface available to future Crack agents."""

from ._gateway import (
    call_app_endpoint,
    query_app_map,
    read_source,
    record_finding,
    record_evidence,
    reset_environment,
    submit_hypothesis,
    update_verification_status,
)

__all__ = [
    "read_source",
    "query_app_map",
    "call_app_endpoint",
    "reset_environment",
    "record_evidence",
    "submit_hypothesis",
    "update_verification_status",
    "record_finding",
]
