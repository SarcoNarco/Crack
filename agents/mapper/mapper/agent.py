"""Produce a validated app contract from the fixed demo application's source."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field, ValidationError

from ledger.init_db import record_run
from model_router import ModelClient, get_client
from scope_controller import read_source, record_evidence


_SOURCE_PATHS = ("app/main.py", "scripts/seed.py", "app/database.py")
_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "output" / "app_contract.json"
_LEDGER_DATABASE_PATH = Path(__file__).resolve().parents[3] / "data" / "ledger.db"
_DECLARED_SCOPE = "source-only mapping of app-under-test through scope_controller.read_source"


class Route(BaseModel):
    method: str = Field(min_length=1)
    path: str = Field(min_length=1)
    description: str = Field(min_length=1)


class AppContract(BaseModel):
    routes: list[Route]
    roles: list[str]
    assumptions: list[str]


class MapperError(RuntimeError):
    """Raised when the mapper cannot produce a validated app contract."""


def _source_context(source_reader: Callable[[str], str] = read_source) -> str:
    """Read only the fixed source files needed to map the Sprint 1 demo app."""
    return "\n\n".join(
        f"--- {path} ---\n{source_reader(path)}" for path in _SOURCE_PATHS
    )


def _prompt(context: str, *, strict: bool) -> str:
    schema = (
        'Return only JSON matching exactly: {"routes":[{"method":"GET",'
        '"path":"/example","description":"..."}],"roles":["..."],'
        '"assumptions":["..."]}. Every route needs all three string fields.'
    )
    retry = " This is the final retry: do not use Markdown fences or prose." if strict else ""
    return (
        "You are a contained app mapper. Infer the intended API surface only from the "
        "provided source. Do not claim tests, live behavior, exploits, or facts absent from it. "
        "List route decorators, seeded account roles/display names, and uncertain observations. "
        f"{schema}{retry}\n\nSOURCE CONTEXT:\n{context}"
    )


def _parse_contract(raw_response: str) -> AppContract:
    fenced_document = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", raw_response, re.DOTALL)
    json_document = fenced_document.group(1) if fenced_document else raw_response
    try:
        return AppContract.model_validate_json(json_document)
    except (ValidationError, ValueError) as exc:
        raise MapperError("LLM response did not match the app-contract schema") from exc


def _app_version(context: str) -> str:
    """Use a reproducible source fingerprint without inspecting anything outside scope."""
    import hashlib

    return f"source-sha256:{hashlib.sha256(context.encode()).hexdigest()[:16]}"


def _write_contract(contract: AppContract, output_path: Path = _OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(contract.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _record_run(*, run_id: str, started_at: str, status: str, app_version: str) -> None:
    record_run(
        run_id=run_id,
        app_version=app_version,
        environment_snapshot_id="source-only",
        agent_role="mapper",
        declared_scope=_DECLARED_SCOPE,
        start_time=started_at,
        end_time=datetime.now(UTC).isoformat(),
        token_budget=0,
        time_budget=0,
        status=status,
        database_path=_LEDGER_DATABASE_PATH,
    )


def _failure_summary(raw_response: str) -> str:
    """Keep diagnostic evidence bounded while retaining the raw failed response."""
    return json.dumps({"raw_llm_response": raw_response}, ensure_ascii=False)


def run_mapper(
    *,
    client: ModelClient | None = None,
    source_reader: Callable[[str], str] = read_source,
    output_path: Path = _OUTPUT_PATH,
) -> AppContract:
    """Perform one source-only mapper pass, with exactly one schema retry."""
    started_at = datetime.now(UTC).isoformat()
    run_id = f"mapper:{uuid.uuid4()}"
    context = _source_context(source_reader)
    app_version = _app_version(context)
    model_client = client or get_client("mapper")
    last_raw_response = ""

    for attempt in range(2):
        last_raw_response = model_client.complete(
            [{"role": "user", "content": _prompt(context, strict=attempt == 1)}]
        )
        try:
            contract = _parse_contract(last_raw_response)
        except MapperError:
            continue

        _write_contract(contract, output_path)
        _record_run(run_id=run_id, started_at=started_at, status="completed", app_version=app_version)
        record_evidence(
            run_id=run_id,
            sequence_number=1,
            action_type="app_contract_created",
            request_response_summary=json.dumps(
                {"route_count": len(contract.routes), "role_count": len(contract.roles)}, sort_keys=True
            ),
            artifact_reference=str(output_path),
            policy_decision="allowed",
        )
        return contract

    _record_run(run_id=run_id, started_at=started_at, status="failed", app_version=app_version)
    record_evidence(
        run_id=run_id,
        sequence_number=1,
        action_type="app_contract_schema_failure",
        request_response_summary=_failure_summary(last_raw_response),
        artifact_reference=str(output_path),
        policy_decision="blocked",
    )
    raise MapperError("Mapper failed after exactly one schema retry; malformed LLM output was recorded")
