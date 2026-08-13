from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mapper import MapperError, run_mapper
from mapper import agent
from scope_controller import _gateway


VALID_CONTRACT = {
    "routes": [
        {"method": "GET", "path": "/health", "description": "Health status."},
        {"method": "GET", "path": "/records/{record_id}", "description": "Read a record."},
    ],
    "roles": ["Account A", "Account B"],
    "assumptions": ["The two seeded display names represent the available roles."],
}


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        return self.responses.pop(0)


@pytest.fixture
def temporary_ledger(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    database_path = tmp_path / "ledger.db"
    monkeypatch.setattr(_gateway, "_LEDGER_DATABASE_PATH", database_path)
    real_record_run = agent.record_run

    def record_test_run(**kwargs: object) -> None:
        kwargs["database_path"] = database_path
        real_record_run(**kwargs)

    monkeypatch.setattr(agent, "record_run", record_test_run)
    return database_path


def test_mapper_successfully_validates_and_writes_contract(
    temporary_ledger: Path, tmp_path: Path
) -> None:
    output_path = tmp_path / "app_contract.json"
    client = FakeClient([f"```json\n{json.dumps(VALID_CONTRACT)}\n```"])

    contract = run_mapper(client=client, output_path=output_path)

    assert contract.model_dump() == VALID_CONTRACT
    assert json.loads(output_path.read_text(encoding="utf-8")) == VALID_CONTRACT
    assert len(client.messages) == 1
    with sqlite3.connect(temporary_ledger) as connection:
        assert connection.execute("SELECT status, agent_role FROM run").fetchone() == ("completed", "mapper")
        assert connection.execute("SELECT action_type FROM event").fetchone() == ("app_contract_created",)


def test_mapper_retries_once_then_succeeds(temporary_ledger: Path, tmp_path: Path) -> None:
    client = FakeClient(["not JSON", json.dumps(VALID_CONTRACT)])

    contract = run_mapper(client=client, output_path=tmp_path / "app_contract.json")

    assert contract.roles == ["Account A", "Account B"]
    assert len(client.messages) == 2
    assert "final retry" in client.messages[1][0]["content"]


def test_mapper_records_raw_failure_after_exactly_one_retry(
    temporary_ledger: Path, tmp_path: Path
) -> None:
    client = FakeClient(["first bad response", "second raw malformed response"])

    with pytest.raises(MapperError, match="exactly one schema retry"):
        run_mapper(client=client, output_path=tmp_path / "app_contract.json")

    assert len(client.messages) == 2
    with sqlite3.connect(temporary_ledger) as connection:
        assert connection.execute("SELECT status FROM run").fetchone() == ("failed",)
        event = connection.execute(
            "SELECT action_type, request_response_summary, policy_decision FROM event"
        ).fetchone()
    assert event[0] == "app_contract_schema_failure"
    assert json.loads(event[1]) == {"raw_llm_response": "second raw malformed response"}
    assert event[2] == "blocked"
