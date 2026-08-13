"""Minimal Sprint 0 coordinator service."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ledger.init_db import initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database(os.getenv("LEDGER_DB_PATH", "data/ledger.db"))
    yield


app = FastAPI(title="Crack Coordinator", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
