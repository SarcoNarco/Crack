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

VALID_WORKFLOW_RULE = {
    "rule_id": "approval_before_publish",
    "account": "account_a",
    "states": ["draft", "approved", "published"],
    "list_route": "/work-items/mine",
    "approve_route": "/work-items/{work_item_id}/approve",
    "publish_route": "/work-items/{work_item_id}/publish",
    "required_predecessor": "approved",
    "invalid_predecessor": "draft",
}


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.messages: list[list[dict[str, str]]] = []
        self.requests: list[dict[str, object]] = []

    def complete(self, messages: list[dict[str, str]], **kwargs: object) -> str:
        self.messages.append(messages)
        self.requests.append(kwargs)
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

    assert contract.model_dump() == {**VALID_CONTRACT, "workflow_rules": []}
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        **VALID_CONTRACT,
        "workflow_rules": [],
    }
    assert len(client.messages) == 1
    assert client.requests == [{"response_format": {"type": "json_object"}}]
    with sqlite3.connect(temporary_ledger) as connection:
        assert connection.execute("SELECT status, agent_role FROM run").fetchone() == ("completed", "mapper")
        assert connection.execute("SELECT action_type FROM event").fetchone() == ("app_contract_created",)


def test_mapper_retries_once_then_succeeds(temporary_ledger: Path, tmp_path: Path) -> None:
    client = FakeClient(["not JSON", json.dumps(VALID_CONTRACT)])

    contract = run_mapper(client=client, output_path=tmp_path / "app_contract.json")

    assert contract.roles == ["Account A", "Account B"]
    assert len(client.messages) == 2
    assert client.requests == [
        {"response_format": {"type": "json_object"}},
        {"response_format": {"type": "json_object"}},
    ]
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
    assert json.loads(event[1]) == {
        "raw_response_characters": len("second raw malformed response"),
        "raw_response_sha256": "57f9240c439b59cc83dc798ef46ff904ba4b91a38ff76682d637f289ee4ff93f",
    }
    assert event[2] == "blocked"


def test_mapper_accepts_a_complete_declared_workflow_rule(
    temporary_ledger: Path, tmp_path: Path
) -> None:
    contract_data = {
        **VALID_CONTRACT,
        "workflow_rules": [VALID_WORKFLOW_RULE],
    }

    contract = run_mapper(
        client=FakeClient([json.dumps(contract_data)]), output_path=tmp_path / "app_contract.json"
    )

    assert contract.workflow_rules[0].model_dump(mode="json") == VALID_WORKFLOW_RULE


@pytest.mark.parametrize(
    "workflow_rule",
    [
        {key: value for key, value in VALID_WORKFLOW_RULE.items() if key != "publish_route"},
        {**VALID_WORKFLOW_RULE, "states": ["approved", "draft", "published"]},
        {**VALID_WORKFLOW_RULE, "publish_route": "/outside/{work_item_id}/publish"},
        {**VALID_WORKFLOW_RULE, "host": "https://outside.example"},
    ],
)
def test_mapper_rejects_incomplete_or_out_of_contract_workflow_rules(
    temporary_ledger: Path, tmp_path: Path, workflow_rule: dict[str, object]
) -> None:
    client = FakeClient([
        json.dumps({**VALID_CONTRACT, "workflow_rules": [workflow_rule]}),
        json.dumps({**VALID_CONTRACT, "workflow_rules": [workflow_rule]}),
    ])

    with pytest.raises(MapperError, match="exactly one schema retry"):
        run_mapper(client=client, output_path=tmp_path / "app_contract.json")
