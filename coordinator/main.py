"""Fixed loopback coordinator and observable canonical demo API."""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Body, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from coordinator.live_events import ActiveRunError, LiveRunManager, ReplayError
from ledger.init_db import initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database(os.getenv("LEDGER_DB_PATH", "data/ledger.db"))
    yield


class StartDemoRequest(BaseModel):
    """The browser may send no body or one fixed confirmation value."""

    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["start-contained-demo"] | None = None


def create_app(manager: LiveRunManager | None = None) -> FastAPI:
    application = FastAPI(title="Crack Coordinator", lifespan=lifespan)
    application.state.live_runs = manager or LiveRunManager()

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/api/demo-runs", status_code=status.HTTP_202_ACCEPTED)
    def start_demo(payload: StartDemoRequest | None = Body(default=None)) -> dict[str, object]:
        del payload
        try:
            session_id = application.state.live_runs.start()
        except ActiveRunError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return application.state.live_runs.status(session_id)

    @application.get("/api/demo-runs/{session_id}")
    def demo_status(session_id: str) -> dict[str, object]:
        try:
            return application.state.live_runs.status(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid demo session ID") from exc
        except ReplayError as exc:
            raise HTTPException(status_code=404, detail="demo session was not found or is unreadable") from exc

    @application.get("/api/demo-runs/{session_id}/events")
    async def demo_events(
        session_id: str,
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            after_sequence = -1 if last_event_id is None else int(last_event_id)
            if after_sequence < -1:
                raise ValueError
            journal = application.state.live_runs.journal(session_id)
            journal.replay(after_sequence=after_sequence)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid session or Last-Event-ID") from exc
        except ReplayError as exc:
            raise HTTPException(status_code=500, detail="presentation replay failed validation") from exc

        async def stream():
            cursor = after_sequence
            idle_cycles = 0
            while True:
                if await request.is_disconnected():
                    return
                try:
                    events = journal.replay(after_sequence=cursor)
                except ReplayError:
                    return
                if events:
                    idle_cycles = 0
                    for event in events:
                        cursor = event.sequence
                        yield f"id: {event.sequence}\ndata: {event.model_dump_json()}\n\n"
                        if event.type in {"session.completed", "session.failed"}:
                            return
                else:
                    existing = journal.replay()
                    if existing and existing[-1].type in {"session.completed", "session.failed"}:
                        return
                    idle_cycles += 1
                    if idle_cycles >= 60:
                        yield ": keep-alive\n\n"
                        idle_cycles = 0
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @application.get("/api/demo-runs/{session_id}/report")
    def demo_report(session_id: str) -> FileResponse:
        try:
            path = application.state.live_runs.report_path(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid demo session ID") from exc
        except ReplayError as exc:
            raise HTTPException(status_code=404, detail="generated report is unavailable") from exc
        return FileResponse(
            path,
            media_type="text/html; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'",
            },
        )

    return application


app = create_app()
