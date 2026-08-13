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
