"""HTTP for Standup: list and read formal meetings, replay them, stream one live (resumable), answer its questions, hand it to the autopilot or take it back.

The live view also arrives on the ordinary workspace stream as `standup.event`; the stream here is for a screen that watches one meeting and wants to resume exactly where it
stopped (`?after=<sequence>` or the standard `Last-Event-ID` header), with heartbeats and no duplicates."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from gateway import commands
from gateway.runner import Conflict, WorkspaceRun
from standup.errors import InvalidEvent, StandupError, StoreError, UnknownMeeting
from standup.presentation import build_view
from standup.transcript import render_transcript

log = logging.getLogger("gateway.standup")
MAX_EVENTS = 1000
OVER = {"meeting_ended", "meeting_timed_out", "meeting_cancelled"}  # after one of these nothing more happens in a meeting: its stream says "end" and closes


def register(app: FastAPI, workspace: Callable[[Request, str], tuple[Optional[WorkspaceRun], Optional[JSONResponse]]], problem: Callable[[int, str, str], JSONResponse]) -> None:
    def fail(exc: Exception) -> JSONResponse:
        if isinstance(exc, UnknownMeeting):
            return problem(404, "not_found", str(exc))
        if isinstance(exc, StoreError):
            return problem(500, "store_error", str(exc))
        if isinstance(exc, StandupError):
            return problem(400 if isinstance(exc, InvalidEvent) else 409, "invalid", str(exc))
        raise exc

    @app.get("/workspace/{workspace_id}/standup/meetings")
    async def meetings(request: Request, workspace_id: str, record: Optional[str] = None):
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        try:
            svc = run.standup.reader(record)
            rows = []
            for m in await asyncio.to_thread(svc.meetings):
                st = svc.state(m.meeting_id)
                rows.append({**m.model_dump(mode="json"), "open_questions": len(st.open_questions()), "decisions": len(st.decisions), "action_items": len(st.actions),
                             "participants": len([p for p in st.participants.values() if p.status.value != "left"]), "last_sequence": st.last_sequence})
        except StandupError as exc:
            return fail(exc)
        return {"record": record or run.standup.tag, "records": run.standup.runs(), "autopilot": run.standup.autopilot, "meetings": rows}

    @app.get("/workspace/{workspace_id}/standup/meetings/{meeting_id}")
    async def meeting(request: Request, workspace_id: str, meeting_id: str, record: Optional[str] = None, at: Optional[int] = None):
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        try:
            svc = run.standup.reader(record)
            state = svc.state_at(meeting_id, at) if at is not None else svc.state(meeting_id)
            if state.meeting is None:
                raise UnknownMeeting(f"no meeting {meeting_id!r}")
            now = state.last_timestamp if (at is not None or state.meeting.ended_at) and state.last_timestamp else datetime.now(timezone.utc)
            return {"view": build_view(state, now).model_dump(mode="json"), "lastSequence": state.last_sequence, "record": record or run.standup.tag}
        except StandupError as exc:
            return fail(exc)

    @app.get("/workspace/{workspace_id}/standup/meetings/{meeting_id}/events")
    async def events(request: Request, workspace_id: str, meeting_id: str, after: int = 0, limit: int = 500, record: Optional[str] = None):
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        try:
            found = await asyncio.to_thread(run.standup.reader(record).events, meeting_id, max(0, after))
        except StandupError as exc:
            return fail(exc)
        page = found[: max(1, min(limit, MAX_EVENTS))]
        return {"meetingId": meeting_id, "events": [e.wire() for e in page], "more": len(found) > len(page), "lastSequence": page[-1].sequence_number if page else after}

    @app.get("/workspace/{workspace_id}/standup/meetings/{meeting_id}/transcript")
    async def transcript(request: Request, workspace_id: str, meeting_id: str, record: Optional[str] = None):
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        try:
            found = await asyncio.to_thread(run.standup.reader(record).events, meeting_id)
        except StandupError as exc:
            return fail(exc)
        if not found:
            return problem(404, "not_found", f"no meeting {meeting_id!r}")
        return PlainTextResponse(render_transcript(found), media_type="text/plain; charset=utf-8")

    @app.get("/workspace/{workspace_id}/standup/meetings/{meeting_id}/stream")
    async def stream(request: Request, workspace_id: str, meeting_id: str, after: Optional[int] = None):
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        header = request.headers.get("last-event-id", "")
        resume = after if after is not None else (int(header) if header.isdigit() else 0)
        hub = run.standup
        try:
            hub.service.state(meeting_id)
        except StandupError as exc:
            return fail(exc)
        queue = hub.subscribe(meeting_id)  # subscribe first, then read what was missed, so nothing falls between the two
        try:
            backlog = hub.service.events(meeting_id, resume)
        except StandupError as exc:
            hub.unsubscribe(queue)
            return fail(exc)

        def frame(e: Any) -> str:
            return f"id: {e.sequence_number}\ndata: {json.dumps(e.wire(), ensure_ascii=False)}\n\n"

        async def body() -> AsyncIterator[str]:
            last = resume
            try:
                yield "retry: 2000\n\n"
                for e in backlog:
                    last = e.sequence_number
                    yield frame(e)
                    if e.event_type in OVER:
                        yield "event: end\ndata: {}\n\n"
                        return
                while True:
                    try:
                        e = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            return
                        yield ": ping\n\n"
                        continue
                    if e is None:
                        return  # fell behind: the screen reconnects with Last-Event-ID and is sent what it missed
                    if e.sequence_number > last:
                        last = e.sequence_number
                        yield frame(e)
                        if e.event_type in OVER:
                            yield "event: end\ndata: {}\n\n"
                            return
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/workspace/{workspace_id}/standup/control")
    async def control(request: Request, workspace_id: str):
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        try:
            body = await request.json()
        except ValueError:
            return problem(400, "invalid_json", "The request was not valid JSON.")
        mode = body.get("mode") if isinstance(body, dict) else None
        if mode not in ("human", "autopilot"):
            return problem(400, "invalid", "mode must be 'human' or 'autopilot'.")
        told = await asyncio.to_thread(run.standup.set_control, mode == "autopilot")
        log.warning("Business SME control: %s (%d open meeting%s told)", mode, told, "" if told == 1 else "s")
        return {"mode": mode, "meetingsTold": told}

    @app.post("/workspace/{workspace_id}/standup/meetings/{meeting_id}/answer")
    async def answer(request: Request, workspace_id: str, meeting_id: str):
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        try:
            body = await request.json()
        except ValueError:
            return problem(400, "invalid_json", "The request was not valid JSON.")
        qid, text = (body.get("questionId") if isinstance(body, dict) else None), (body.get("answer") if isinstance(body, dict) else None)
        if not isinstance(qid, str) or not isinstance(text, str) or not text.strip():
            return problem(400, "invalid", "questionId and a non-empty answer are needed.")
        try:
            state = run.standup.service.state(meeting_id)
        except StandupError as exc:
            return fail(exc)
        question = state.questions.get(qid)
        if question is None or question.status.value != "open":
            return problem(409, "conflict", "That question is not waiting for an answer.")
        if run.questions.answer(text.strip(), qid) is None:
            return problem(409, "conflict", "That question is no longer waiting for you.")
        return {"accepted": True}

    @app.post("/workspace/{workspace_id}/standup/meetings/{meeting_id}/direct")
    async def direct(request: Request, workspace_id: str, meeting_id: str):
        """Interrupt or redirect: the Business SME says something to the team. It travels the same way as a directive typed into the control plane."""
        run, error = workspace(request, workspace_id)
        if error is not None:
            return error
        assert run is not None
        try:
            body = await request.json()
        except ValueError:
            return problem(400, "invalid_json", "The request was not valid JSON.")
        text = (body.get("text") if isinstance(body, dict) else "") or ""
        if not text.strip():
            return problem(400, "invalid", "text is needed.")
        try:
            result = await commands.execute(run, {"type": "sme.directive.submit", "workspaceId": workspace_id, "directive": text.strip()})
        except Conflict as exc:
            return problem(409, "conflict", str(exc))
        return result.dump()
