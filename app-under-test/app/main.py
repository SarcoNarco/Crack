"""A tiny notes app used only as Crack's disposable Sprint 1 target."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from .database import connect, initialize_database


class LoginRequest(BaseModel):
    username: str
    password: str


class RecordUpdate(BaseModel):
    title: str
    body: str


def current_account(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ")
    with connect() as connection:
        account = connection.execute(
            "SELECT id, username, display_name FROM accounts WHERE token = ?", (token,)
        ).fetchone()

    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    return dict(account)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Demo Notes App", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/login")
def login(request: LoginRequest) -> dict[str, str]:
    with connect() as connection:
        account = connection.execute(
            "SELECT token, display_name FROM accounts WHERE username = ? AND password = ?",
            (request.username, request.password),
        ).fetchone()

    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return {"access_token": account["token"], "account": account["display_name"]}


@app.get("/records/mine")
def get_my_records(account: dict[str, str] = Depends(current_account)) -> dict[str, list[dict[str, str]]]:
    """Return the authenticated account's records for ordinary in-app navigation."""
    with connect() as connection:
        records = connection.execute(
            """
            SELECT id, owner_account_id, title, body
            FROM records
            WHERE owner_account_id = ?
            ORDER BY id
            """,
            (account["id"],),
        ).fetchall()
    return {"records": [dict(record) for record in records]}


def _owned_work_item(work_item_id: str, account_id: str):
    with connect() as connection:
        item = connection.execute(
            "SELECT id, owner_account_id, title, state FROM work_items WHERE id = ? AND owner_account_id = ?",
            (work_item_id, account_id),
        ).fetchone()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
    return dict(item)


@app.get("/work-items/mine")
def get_my_work_items(account: dict[str, str] = Depends(current_account)) -> dict[str, list[dict[str, str]]]:
    """Return the caller's workflow items for ordinary in-app navigation."""
    with connect() as connection:
        items = connection.execute(
            "SELECT id, owner_account_id, title, state FROM work_items WHERE owner_account_id = ? ORDER BY id",
            (account["id"],),
        ).fetchall()
    return {"work_items": [dict(item) for item in items]}


@app.post("/work-items/{work_item_id}/approve")
def approve_work_item(work_item_id: str, account: dict[str, str] = Depends(current_account)) -> dict[str, str]:
    """Advance only a draft work item to approved."""
    item = _owned_work_item(work_item_id, account["id"])
    if item["state"] != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft work items can be approved")
    with connect() as connection:
        connection.execute("UPDATE work_items SET state = 'approved' WHERE id = ?", (work_item_id,))
    return {"id": work_item_id, "previous_state": "draft", "state": "approved"}


@app.post("/work-items/{work_item_id}/publish")
def publish_work_item(work_item_id: str, account: dict[str, str] = Depends(current_account)) -> dict[str, str]:
    """Publish an owned item; intentionally missing the required approved-state check."""
    item = _owned_work_item(work_item_id, account["id"])
    if item["state"] == "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Published work items are terminal")
    # Intentional Sprint 7 defect: a draft item incorrectly bypasses approval here.
    with connect() as connection:
        connection.execute("UPDATE work_items SET state = 'published' WHERE id = ?", (work_item_id,))
    return {"id": work_item_id, "previous_state": item["state"], "state": "published"}


@app.get("/records/{record_id}")
def get_record(record_id: str, _: dict[str, str] = Depends(current_account)) -> dict[str, str]:
    """Return a note after confirming the caller has an authenticated session."""
    with connect() as connection:
        record = connection.execute(
            "SELECT id, owner_account_id, title, body FROM records WHERE id = ?", (record_id,)
        ).fetchone()

    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
    return dict(record)


@app.put("/records/{record_id}")
def update_record(
    record_id: str, update: RecordUpdate, account: dict[str, str] = Depends(current_account)
) -> dict[str, str]:
    """Write paths correctly restrict records to their owner."""
    with connect() as connection:
        record = connection.execute(
            "SELECT id FROM records WHERE id = ? AND owner_account_id = ?",
            (record_id, account["id"]),
        ).fetchone()
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
        connection.execute(
            "UPDATE records SET title = ?, body = ? WHERE id = ?", (update.title, update.body, record_id)
        )
    return {"id": record_id, "status": "updated"}


@app.delete("/records/{record_id}")
def delete_record(record_id: str, account: dict[str, str] = Depends(current_account)) -> dict[str, str]:
    """Write paths correctly restrict records to their owner."""
    with connect() as connection:
        record = connection.execute(
            "SELECT id FROM records WHERE id = ? AND owner_account_id = ?",
            (record_id, account["id"]),
        ).fetchone()
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")
        connection.execute("DELETE FROM records WHERE id = ?", (record_id,))
    return {"id": record_id, "status": "deleted"}
