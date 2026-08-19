from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from scripts.seed import seed


ACCOUNT_A = {"Authorization": "Bearer token-account-a-fixed"}
ACCOUNT_B = {"Authorization": "Bearer token-account-b-fixed"}
ITEM_ID = "release-account-a-001"


def test_seed_is_idempotent_and_exposes_a_draft_work_item(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "demo.db"))
    seed()
    seed()

    with TestClient(app) as client:
        response = client.get("/work-items/mine", headers=ACCOUNT_A)

    assert response.status_code == 200
    assert response.json()["work_items"] == [
        {
            "id": ITEM_ID,
            "owner_account_id": "account-a",
            "title": "Account A release checklist",
            "state": "draft",
        }
    ]


def test_approved_work_item_can_be_published(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "demo.db"))
    seed()

    with TestClient(app) as client:
        approved = client.post(f"/work-items/{ITEM_ID}/approve", headers=ACCOUNT_A)
        repeated_approval = client.post(f"/work-items/{ITEM_ID}/approve", headers=ACCOUNT_A)
        published = client.post(f"/work-items/{ITEM_ID}/publish", headers=ACCOUNT_A)

    assert approved.json() == {"id": ITEM_ID, "previous_state": "draft", "state": "approved"}
    assert repeated_approval.status_code == 409
    assert published.json() == {"id": ITEM_ID, "previous_state": "approved", "state": "published"}


def test_draft_publish_is_the_one_intentional_invalid_transition(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "demo.db"))
    seed()

    with TestClient(app) as client:
        published = client.post(f"/work-items/{ITEM_ID}/publish", headers=ACCOUNT_A)
        repeated_publish = client.post(f"/work-items/{ITEM_ID}/publish", headers=ACCOUNT_A)
        terminal_approval = client.post(f"/work-items/{ITEM_ID}/approve", headers=ACCOUNT_A)

    assert published.json() == {"id": ITEM_ID, "previous_state": "draft", "state": "published"}
    assert repeated_publish.status_code == 409
    assert terminal_approval.status_code == 409


def test_workflow_operations_remain_owned_by_the_authenticated_account(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "demo.db"))
    seed()

    with TestClient(app) as client:
        response = client.post(f"/work-items/{ITEM_ID}/publish", headers=ACCOUNT_B)

    assert response.status_code == 404
