"""One workspace's run: the kickoff meeting, your acceptance of the documents, then the sprints, driven the same way `python -m council run` drives them.

The run owns the questions waiting for you and the team engine's desk, and it is the only place that starts backend work. It calls the same public
functions the terminal pipeline calls (`run_meeting`, `TeamEngine`, `config_from_args`, `carry_repo`); nothing in the backend is changed for it."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from gateway.bridges import KICKOFF, MeetingBridge, Questions, TeamBridge, publish_documents, read_text
from gateway.models import PHASES
from gateway.narrator import Narrator, agent_id, clip
from gateway.projection import Projection

log = logging.getLogger("gateway.runner")


class Conflict(Exception):
    """The request cannot be done in the workspace's current state (HTTP 409)."""


@dataclass
class Deps:
    """Everything the run needs from outside, so tests can supply scripted models. The defaults are the real ones (Gemini, from the environment)."""

    meeting_settings: Callable[[], Any]
    meeting_llm: Callable[[Any], Any]
    team_llm: Optional[Any] = None  # a scripted client in tests; None means the real model through the settings' key


def default_deps() -> Deps:
    from meetings.config import load_settings
    from meetings.gemini_client import GeminiClient

    return Deps(meeting_settings=load_settings, meeting_llm=lambda settings: GeminiClient(settings))


def project_name_from(brief: str, title: Optional[str]) -> str:
    if title and title.strip():
        return title.strip()[:80]
    for line in brief.splitlines():
        cleaned = re.sub(r"^[#\s>*-]+", "", line).strip()
        cleaned = re.sub(r"(?i)^project\s*:\s*", "", cleaned).strip()
        if cleaned:
            return cleaned[:80]
    return "New project"


def approved_by(text: str) -> tuple[bool, str]:
    """An answer to an approval card: 'Approve' (or yes / ok / accept) approves; anything else declines and is the feedback."""
    plain = text.strip()
    low = plain.lower()
    if re.match(r"^(approve|approved|accept|yes|y|ok|okay|lgtm)\b", low):
        return True, ""
    feedback = re.sub(r"(?i)^(decline|declined|reject|no)\s*[:\-]?\s*", "", plain).strip()
    return False, feedback


class WorkspaceRun:
    def __init__(self, workspace_id: str, projection: Projection, settings: Any, deps: Deps) -> None:
        self.workspace_id, self.p, self.settings, self.deps = workspace_id, projection, settings, deps
        self.run_no = 0
        self.state = "idle"  # idle | meeting | building | done | failed | stopped
        self.narrator = Narrator(projection)
        self.narrator.seed()
        self.questions = Questions(self.narrator)
        self.engine: Any = None
        self.meeting_dir: Optional[Path] = None
        self.project_name = ""
        self.document_accepted = False
        self.document_revisions = 0
        self.docs_approval_ids: set[str] = set()
        self.queued_notes: list[str] = []
        self.error: Optional[str] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.task: Optional[asyncio.Task] = None
        self.background: set[asyncio.Task] = set()
        self.phase_log: list[str] = []

    # ------------------------------------------------------------------ state

    @property
    def active(self) -> bool:
        return self.state in ("meeting", "building")

    @property
    def desk(self):
        return self.engine.agile.desk if self.engine is not None and self.engine.agile is not None else None

    def set_phase(self, phase: str) -> None:
        if phase in PHASES and self.p.phase != phase:
            self.p.emit("phase.changed", {"phaseId": phase})
            self.phase_log.append(phase)

    def spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    # ------------------------------------------------------------------ starting

    async def start(self, brief: str, title: Optional[str] = None, repo: Optional[str] = None, constraints: Optional[list[str]] = None) -> None:
        from meetings.meeting import meeting_dir
        from meetings.models import MeetingInput

        if self.active:
            raise Conflict("A run is already in progress in this workspace.")
        # The repository is cloned during the pod meeting, so a private one needs the GitHub CLI's credentials from the very start, as in the terminal.
        from team.cli import use_github_credentials

        use_github_credentials()
        self.loop = asyncio.get_running_loop()
        self.run_no += 1
        self.narrator = Narrator(self.p, "" if self.run_no == 1 else f"r{self.run_no}-")
        self.narrator.seed()
        self.questions = Questions(self.narrator)
        self.engine, self.error = None, None
        self.document_accepted, self.document_revisions, self.docs_approval_ids = False, 0, set()
        self.project_name = project_name_from(brief, title)
        target = (repo or self.settings.repo or "").strip()
        is_url = target.lower().startswith(("http://", "https://"))
        name = self.project_name
        inp = MeetingInput(project_name=name, problem=brief.strip(), constraints=[c.strip() for c in (constraints or []) if isinstance(c, str) and c.strip()], repo_path=target if target and not is_url else None,
                           github_url=target if is_url else None, output_dir=str(self.settings.output_dir))
        if (meeting_dir(inp) / "meeting.json").exists():  # the same project name again: a new folder, not a clash
            inp = inp.model_copy(update={"project_name": f"{name} {time.strftime('%Y%m%d-%H%M%S')}"})
        self.meeting_dir = meeting_dir(inp)
        self.state = "meeting"
        self.set_phase("brainstorm")
        n = self.narrator
        n.meet(KICKOFF, f"Kickoff meeting: {self.project_name}", "live")
        n.say(KICKOFF, "human", clip(brief, 1200))
        n.system(KICKOFF, f"Starting the pod meeting for \"{self.project_name}\".")
        self.task = asyncio.ensure_future(self._run(inp))

    async def _run(self, inp: Any) -> None:
        n = self.narrator
        try:
            await self._meeting(inp)
            await self._build(inp)
            self.state = "done"
        except asyncio.CancelledError:
            self.state = "stopped"
            n.system("team", "The run was stopped.")
            raise
        except Exception as exc:  # noqa: BLE001 - shown to the person; the workspace stays usable
            from team.agile.playbook import AgileStopped

            self.state, self.error = "failed", f"{type(exc).__name__}: {exc}"
            n.system("team", "The documents were not accepted, so nothing was built." if isinstance(exc, AgileStopped) else f"The run stopped: {clip(str(exc), 400)}")
            log.exception("run failed")
        finally:
            for agent in list(self.p.agents):
                if agent not in ("agent-sm", "sme-01") and self.p.agents[agent].get("status") in ("active", "speaking"):
                    n.agent(agent, status="idle", activeTask=None)
            n.agent("human", status="idle", activeTask=None)
            n.meet(KICKOFF, f"Kickoff meeting: {self.project_name}", "completed")

    async def _meeting(self, inp: Any) -> None:
        from meetings.meeting import run_meeting

        settings = self.deps.meeting_settings()
        bridge = MeetingBridge(self)
        result = await run_meeting(inp, settings, self.deps.meeting_llm(settings), bridge, interactive=True, a2a=getattr(self.settings, "a2a", True))
        self.meeting_dir = result.out_dir
        bridge.finished(result.report.passed)
        publish_documents(self, "draft")

    async def _build(self, inp: Any) -> None:
        from council.pipeline import carry_repo
        from meetings.config import load_settings  # noqa: F401  (the real key is read by the engine when no scripted client is given)
        from team.cli import add_build_arguments, config_from_args
        from team.engine import TeamEngine

        assert self.meeting_dir is not None
        parser = argparse.ArgumentParser()
        parser.add_argument("directory")
        add_build_arguments(parser)
        args = parser.parse_args([str(self.meeting_dir)])
        args.repo = inp.github_url or inp.repo_path or None
        args.no_memory = not getattr(self.settings, "memory", True)
        args.unattended = bool(getattr(self.settings, "unattended", False))
        args.repair_rounds = int(getattr(self.settings, "repair_rounds", 2))
        carry_repo(args, self.meeting_dir)
        config, _ = config_from_args(args)
        repo = (args.repo or "").strip()
        source = Path(repo).expanduser() if repo and Path(repo).expanduser().is_dir() else None
        meeting_settings = self.deps.meeting_settings()
        bridge = TeamBridge(self)
        engine = TeamEngine(
            self.meeting_dir, self.meeting_dir / "team", llm=self.deps.team_llm, api_key=getattr(meeting_settings, "api_key", None),
            model=getattr(meeting_settings, "model", None), source=source, config=config, on_event=bridge.handle,
        )
        self.engine, self.state = engine, "building"
        for note in self.queued_notes:
            if engine.agile is not None:
                engine.agile.desk.note(note)
        self.queued_notes.clear()
        result = await engine.run()
        publish_documents(self, "approved", human_accepted=True)
        report = read_text(self.meeting_dir / "team_report.md")
        if report:
            self.p.emit("artifact.updated", {
                "id": "art-team-report", "title": "Team report", "filename": "team_report.md", "status": "approved", "currentVersion": "v1.0",
                "acceptedCount": 0, "totalRequired": 0, "markdownContent": report, "acceptedBy": [],
            })
        self.set_phase("ship")
        self.narrator.system("team", f"Done: {sum(1 for f in result.features if f.status == 'merged')}/{len(result.features)} features merged; "
                             f"verification {'passed' if result.passed else 'did not pass'}. Review {result.final_branch}; nothing was merged into main.")

    # ------------------------------------------------------------------ the human

    def resolve_approval(self, approval_id: str, text: str) -> None:
        desk = self.desk
        if desk is None:
            return
        approved, feedback = approved_by(text)
        try:
            desk.answer(approval_id, approved, feedback)
        except KeyError:
            log.warning("approval %s was already answered", approval_id)

    def agent_to_dev(self, agent: str) -> Optional[str]:
        """agent-03 -> DEV_3 (the name the team engine knows the developer by)."""
        match = re.fullmatch(r"agent-(\d+)", agent)
        if not match or self.engine is None:
            return None
        name = f"DEV_{int(match.group(1))}"
        return name if name in self.engine.developers else None

    async def say_to_team(self, text: str, kind: Optional[str] = None) -> None:
        desk = self.desk
        if desk is None:
            return
        await desk.interrupt()
        try:
            await desk.say(text, kind)
        finally:
            await desk.release()

    async def stop(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except BaseException:  # noqa: BLE001
                pass
        for task in list(self.background):
            task.cancel()
