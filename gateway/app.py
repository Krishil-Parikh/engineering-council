"""The HTTP application: the three endpoints of the frontend contract, plus a health check and (optionally) the built frontend itself.

    GET  /workspace/{id}/snapshot   the full canonical snapshot
    POST /workspace/{id}/commands   one of the eight commands -> {accepted, commandId}
    GET  /workspace/{id}/events     server-sent events, one JSON event per frame

Errors follow the contract: 400 for an invalid command, 401/403 for a missing or wrong token, 404 for an unknown workspace, 409 when the request does
not fit the workspace's state, 429 when commands come too fast."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from gateway import commands
from gateway.config import GatewaySettings
from gateway.logs import heartbeat_line, one_line
from gateway.models import validate_command
from gateway.projection import Projection
from gateway.runner import Conflict, Deps, WorkspaceRun, default_deps


log = logging.getLogger("gateway")


class Hub:
    """The workspaces this gateway serves. The default one always exists; any other id is a 404."""

    def __init__(self, settings: GatewaySettings, deps: Deps) -> None:
        self.settings, self.deps = settings, deps
        self.runs: dict[str, WorkspaceRun] = {}
        self._calls: dict[str, list[float]] = {}
        self.get(settings.workspace_id)

    def get(self, workspace_id: str) -> Optional[WorkspaceRun]:
        if workspace_id in self.runs:
            return self.runs[workspace_id]
        if workspace_id != self.settings.workspace_id:
            return None
        projection = Projection(workspace_id, self.settings.data_dir / workspace_id / "events.jsonl", self.settings.replay_window)
        run = WorkspaceRun(workspace_id, projection, self.settings, self.deps)
        if projection.version and projection.phase not in ("kickoff", "ship"):
            # the gateway was restarted in the middle of a run: it cannot be carried on from here, so say so and offer a fresh start
            run.reset()
            run.narrator.system("team", "The gateway was restarted while a run was in progress, so that run stopped. Start a new project (its files are still in the output folder; resume a build from the terminal with --run-id).")
        self.runs[workspace_id] = run
        return run

    def allow(self, workspace_id: str) -> bool:
        """At most `rate_per_minute` commands per workspace in any minute."""
        now = time.monotonic()
        calls = [t for t in self._calls.get(workspace_id, []) if now - t < 60]
        if len(calls) >= self.settings.rate_per_minute:
            self._calls[workspace_id] = calls
            return False
        calls.append(now)
        self._calls[workspace_id] = calls
        return True

    async def close(self) -> None:
        for run in self.runs.values():
            await run.stop()


async def heartbeat(hub: "Hub", seconds: float) -> None:
    """While a run is going, says so every few seconds, and says what it is waiting for when it goes quiet."""
    while seconds > 0:
        await asyncio.sleep(seconds)
        for run in list(hub.runs.values()):
            line = heartbeat_line(run)
            if line is not None:
                log.log(line[0], "[%s] %s", run.workspace_id, line[1])


def problem(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}, "detail": message})


# Without a token the gateway only listens on this machine, so any local page (any port, localhost or a private address) may call it.
LOCAL_ORIGIN = r"^https?://(localhost|127\.0\.0\.1|\[::1\]|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?$"


def create_app(settings: Optional[GatewaySettings] = None, deps: Optional[Deps] = None) -> FastAPI:
    settings = settings or GatewaySettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.hub = Hub(settings, deps or default_deps())
        beat = asyncio.ensure_future(heartbeat(app.state.hub, settings.heartbeat_seconds))
        yield
        beat.cancel()
        await app.state.hub.close()

    app = FastAPI(title="Engineering Council gateway", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_origin_regex=LOCAL_ORIGIN if settings.token is None else None, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

    def denied(request: Request) -> Optional[JSONResponse]:
        if not settings.token:
            return None
        header = request.headers.get("authorization", "")
        presented = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
        if not presented:
            return problem(401, "unauthorized", "This gateway needs a token.")
        return None if presented == settings.token else problem(403, "forbidden", "That token is not accepted.")

    def workspace(request: Request, workspace_id: str) -> tuple[Optional[WorkspaceRun], Optional[JSONResponse]]:
        refused = denied(request)
        if refused is not None:
            return None, refused
        run = request.app.state.hub.get(workspace_id)
        return (run, None) if run is not None else (None, problem(404, "not_found", f"Unknown workspace: {workspace_id}"))

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "workspace": settings.workspace_id}

    @app.get("/workspace/{workspace_id}/snapshot")
    async def snapshot(request: Request, workspace_id: str):
        run, error = workspace(request, workspace_id)
        return error if error is not None else run.p.snapshot()  # type: ignore[union-attr]

    @app.post("/workspace/{workspace_id}/commands")
    async def post_command(request: Request, workspace_id: str):
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        try:
            body = await request.json()
        except ValueError:
            return problem(400, "invalid_json", "The command was not valid JSON.")
        invalid = validate_command(body)
        if invalid is not None:
            return problem(400, "invalid_command", invalid)
        if body["workspaceId"] != workspace_id:
            return problem(400, "invalid_command", "workspaceId does not match the URL.")
        if not request.app.state.hub.allow(workspace_id):
            return problem(429, "rate_limited", "Too many commands; slow down.")
        summary = one_line({k: v for k, v in body.items() if k not in ("workspaceId", "type")}, 140)
        log.info("browser -> %s %s", body["type"], summary)
        try:
            result = await commands.execute(run, body)
            log.info("   %s", "accepted" if result.accepted else f"declined: {result.note or 'not possible right now'}")
            return result.dump()
        except Conflict as exc:
            log.warning("   refused (409): %s", exc)
            return problem(409, "conflict", str(exc))

    @app.get("/workspace/{workspace_id}/events")
    async def events(request: Request, workspace_id: str):
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        queue = run.p.subscribe()  # subscribe before reading the backlog, so nothing falls between the two
        log.info("browser connected to the event stream (%d watching)", len(run.p._subscribers))
        backlog = run.p.recent(settings.replay_window)

        def frame(event: dict[str, Any]) -> str:
            return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        async def stream() -> AsyncIterator[str]:
            seen: set[str] = set()
            try:
                for event in backlog:
                    seen.add(event["eventId"])
                    yield frame(event)
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            return
                        yield ": ping\n\n"  # keeps proxies and the browser's connection alive; EventSource ignores comments
                        continue
                    if event is None:
                        return  # this client fell behind and was dropped; it reconnects and is replayed what it missed
                    if event["eventId"] not in seen:
                        yield frame(event)
            finally:
                run.p.unsubscribe(queue)
                log.info("browser left the event stream (%d watching)", len(run.p._subscribers))

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if settings.static_dir is not None and Path(settings.static_dir).is_dir():
        app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="frontend")
    return app
