# Plan: connect the Azure_Agent frontend to the Engineering Council backend

## Context

`Azure_Agent-main.zip` (in the repo root) holds a React 19 / Vite / TypeScript frontend, `frontend/agentic-scrum-control-plane`, with two views
(GenUI wizard, Control Plane dashboard). It already talks to its backend only through one interface, `WorkspaceRepository`
(`getSnapshot`, `execute(command)`, `subscribe(onEvent)`), and today runs on an in-memory mock. The frontend team wrote the contract the backend
must satisfy: `docs/backend-contract.md` + `contracts/openapi.workspace.stub.yaml`:

- `GET  /workspace/{id}/snapshot` → full `WorkspaceSnapshot`
- `POST /workspace/{id}/commands` → `{accepted, commandId}` (8 command types)
- `GET  /workspace/{id}/events`   → SSE, one JSON `WorkspaceEvent` per frame (9 event types, `eventId` unique, `version` monotonic)
- errors map to UI states (401/403 permission, 404/409/429/5xx error, stream drop → "disconnected")

Our backend (Python) has no HTTP surface. It is a set of in-process APIs: the pod meeting (`meetings.meeting.run_meeting`, with a `Reporter`
hook class), and the team engine with the agile playbook (`TeamEngine`, `on_event`, `engine.agile.desk` for approvals / interrupt / notes,
`engine.agile.store.state` for sprints / standups / impediments, the A2A audit log).

**Goal:** make the existing frontend drive and display the existing backend, with **zero functionality changes to the backend**. The seam the
frontend already defined becomes a new, additive **gateway** that translates between the two. The backend modules (`harness`, `meetings`, `team`,
`memory`, `council_a2a`, `council`) are not edited.

## What I found

**Frontend: the contract side is clean, the screens are partly scripted.**
- Data-driven: agents, messages (transcript), skills, artifacts, meets, sprints, edges, metrics, PR history all come from the snapshot/events.
- Scripted demo choreography that a real backend would fight:
  - `PRDPhase`: hard-coded accepted ids `agent-01..05`, hard-coded PRD text, **auto-signs-off after 4 s** (would defeat "first documents are
    always accepted by the human").
  - `BuildPhase`: React Flow graph with fixed nodes `agent-01..05` and fixed PR labels; `onFinishBuild` fires from a timer.
  - `GenUIView` itself fires `phase.advance` on timers (after an SME answer, after PRD accept, after build) and uses hard-coded seed message ids
    (`msg-06`, `msg-04`) to mark the SME-question and debate messages.
  - `ReviewPhase` / `ShipPhase` / `ARTIFACTS_LIST` are static copy; `SettingsModal` add/remove agent and skill are local-only.
- `createRepositoryFromConfig` returns `HttpWorkspaceRepository` (SSE) for any non-mock transport. The "websocket" option is documented but not implemented, so SSE is the only transport.
- SSE client facts that shape the gateway: it listens to default `message` events only, de-duplicates by `eventId` per connection, drops events
  with `version` below the snapshot's, and reconnects by creating a **new** `EventSource` (so no `Last-Event-ID`).

**Backend: everything needed is reachable through public hooks.**
- Meeting: `run_meeting(..., reporter=<Reporter subclass>)`; the TUI already subclasses `Reporter` (`stage`, `say`, `publish`, `roster`, `note`, `warn`, `ask`).
  Overriding `ask` is how the Q&A (≤5 product questions) can be answered from a browser.
- Team: `TeamEngine(meeting_dir, root, config, on_event=...)` emits every event we need (`plan`, `feature-*`, `task`, `talk`, `sprint-planned`,
  `standup`, `sprint-review/report/retro`, `doc-sync`, `approval-requested/answered`, `verification`, `final`, …). `engine.agile.desk` exposes
  `answer`, `interrupt`, `say`, `release`, `note`; `engine.brief(dev, text)` delivers a message to a developer over A2A.
- Everything the frontend wants to *show* but the engine does not emit as an event (artifact bodies, git history, roster, tokens) is readable
  from files and `engine.*` attributes (read-only).

## Architecture

New top-level package `gateway/` (FastAPI + uvicorn), one process, started with `python -m gateway`. It never edits backend code; it imports
`meetings` and `team` like `council/` does.

```
browser (Vite app, VITE_TRANSPORT=http-sse)
   │  GET snapshot · POST commands · GET events (SSE)
   ▼
gateway/app.py ── auth/CORS ── routes
   ├─ projection.py   canonical WorkspaceSnapshot + versioned event log (ring buffer + events.jsonl on disk)
   ├─ runner.py       one WorkspaceRun per workspace: IDLE → MEETING → AWAITING_DOCS → BUILDING → REVIEW → DONE/FAILED/STOPPED
   ├─ translate/      backend → contract: meeting.py (Reporter), team.py (engine events), agile.py (AgileState), artifacts.py, agents.py, metrics.py
   ├─ commands.py     contract commands → backend calls (below)
   └─ questions.py    pending human questions (meeting Q&A + approvals) shown as SME cards
        ▼ public APIs only
   meetings.run_meeting · team.TeamEngine (+ agile desk) · council_a2a audit · files in the meeting dir / team sandboxes
```

Workspace id = project slug (default `workspace-demo` from `VITE_WORKSPACE_ID`). An unknown id returns 404 until `sprint.start` creates it. One
active run per workspace; state persisted to `<data>/<workspace>/run.json` so a gateway restart rebuilds the projection from disk
(`events.jsonl`, meeting dir, `agile/state.json`) and resumes with the existing `--run-id` machinery.

## Mappings

**Phase (derived from backend truth, never from the UI):**

| UI phase | Backend state |
|---|---|
| kickoff | no run, or run finished and a new one not started |
| brainstorm | meeting stages 1–7 (blind thinking, conversation, Q&A, rethink, decisions) |
| prd | stages 8–10 done and the first-documents approval is pending (or being revised after feedback) |
| build | documents accepted; sprints running (planning, work days, standups, sprint ceremonies) |
| review | all sprints closed; final verification / repair (`verification` event) |
| ship | `final` event: `final/<run>` pushed, `team_report.md` written (the human still merges to main) |

**Snapshot fields:**
- `agents` ← roster (DEV_1..6 + skill), scrum master (integrator), SME (the human). `status` from `engine.current` / work gate (`active` working,
  `speaking` mid-conversation, `blocked` open impediment, `complete` feature merged, else `idle`); `activeTask` = current task title;
  `claimedSkill` = roster skill; `activeBranch` = `feature/<id>`; `contextUsagePercent` from the developer harness's session tokens vs model window;
  `confidenceScore` has no backend source → omitted (UI defaults), `avatarColor` deterministic per agent.
- `messages` ← meeting `say/publish` lines, A2A `talk` events (planning, votes, conflict talks, standups, briefings), ceremony summaries, human directives. `meetId` per conversation.
- `meets` ← "Kickoff meeting" + one per ceremony (sprint N planning, standup K, review, retro, doc sync) + design-vote meets. `consensusRate` from decisions/votes, `debateIntensity` from dispute and objection counts; `status` live/completed.
- `sprints` ← `AgileState.sprints` (`progress` = delivered/planned tasks, `status` active/closed, `phase` = current ceremony).
- `artifacts` ← `PRD.md`, `Technical_Approach.md`, `Design.md` (body from file; `versions[]` from git history of the integration branch + `docs/agile/CHANGELOG.md`; `acceptedBy` from approvals; status draft → in_review (approval pending) → approved), plus `sprint_report`, `retrospective`, `team_report.md`, and the final-branch note.
- `edges` ← scrum master → feature owner while the feature runs; `latencyMs` from A2A audit `ms`; `isActive` while a conversation is in flight.
- `skills` ← roster skills + lessons-learned skills (`LessonStore.skills_dir`) with `claimedCount`.
- `metrics` ← `totalMessagesToday` (audit entries today), `totalPRs` = merged features, `prHistory` per hour from merge times.

**Events:** every backend event becomes 1..n contract events (`agent.updated`, `message.created`, `meet.updated`, `sprint.updated`, `artifact.updated`, `edge.updated`, `metrics.updated`, `phase.changed`, `skill.updated`) with a gateway-assigned monotonic `version` and unique `eventId`. SSE frames are plain `data: {json}` (default event name). On subscribe the gateway **replays the recent window** (last ~200 events); safe because the client and `applyWorkspaceEvent` are idempotent by `eventId`/`version`, and `processedEventIds` in the snapshot lists the recent ids.

**Commands → backend (all through existing public calls):**

| Command | Backend action |
|---|---|
| `sprint.start {brief}` | create the run: project name from the brief's first line, `MeetingInput`, `run_meeting(... Reporter subclass, a2a=True)` then `TeamEngine` with `AgileConfig(approvals="ask")`. 409 if a run is already active |
| `sme.directive.submit {meetId, directive}` | if a question is pending (meeting Q&A or an approval): answer it (approve / decline + feedback parsed from the card). Otherwise `desk.interrupt()` + `desk.say(text)` + `desk.release()` (note / scope / rethink classified by the scrum master) |
| `prd.accept {artifactId}` | `desk.answer(<first-documents approval>, approved)`; 409 if nothing is pending |
| `message.create` | `desk.note(text)` (delivered at the next standup) |
| `debate.inject {meetId, text}` | a `rethink` directive carrying the challenge text |
| `consensus.force {meetId}` | approves the pending design-vote / approval for that meet; accepted:false if none |
| `agent.task.reassign {agentId, task}` | `engine.brief(dev, …)` over A2A (the developer is told; the plan is not rewritten) |
| `phase.advance {phaseId}` | a *request*, validated against real state: `build` only after docs accepted, `ship` only when the run is finished; otherwise `accepted:false` / 409. `kickoff` after a finished run resets the workspace for a new sprint |

Errors: validation → 400 `{error:{code,message}}`; unknown workspace 404; state conflict 409; per-workspace command rate limit 429; optional bearer token → 401/403.

## Frontend edits (targeted, no redesign; mock transport stays default and its tests stay green)

1. **Config:** `.env` for `http-sse`; gateway base URL; Vite dev proxy or CORS.
2. **Messages carry questions (additive, optional fields):** `kind?: 'question'`, `question?: {id, context, options?}`, `answersQuestion?: id` in `domain/types.ts`. `GenUIView` derives `isQuestionForSME` / answered state from these instead of the hard-coded seed ids; same for the debate flag.
3. **PRDPhase:** render the real PRD / Technical Approach / Design from `snapshot.artifacts` (tabs), show `acceptedBy`, require an explicit Accept (→ `prd.accept`) or "Request changes" (→ directive with feedback). Remove the auto-signoff timer and hard-coded ids when the transport is not mock.
4. **BuildPhase:** nodes and edges from `snapshot.agents` / `snapshot.edges` and sprint progress instead of the fixed `agent-01..05` graph; PR numbers from metrics.
5. **GenUIView:** in http mode stop firing `phase.advance` from timers and stop the "synthesize directive" message chain; the view follows `snapshot.phaseId`. Buttons that stay (Accept PRD, Approve & Ship) send commands and wait for the backend's phase change. Hide "Conclude meet" (the meeting ends itself).
6. **ReviewPhase / ShipPhase:** show verification results, the sprint reports, the final branch name and "merge it yourself" from artifacts instead of static copy.
7. **Optional `sprint.start.title`** (additive) so the project name is not guessed.
8. **SettingsModal:** add/remove agent and skill stay local-only (labelled); the roster is decided by the meeting.
9. Update fixtures/tests to cover both transports; extend `WorkspaceShell.states` tests for the new question cards.

## Implementation phases (each ends green and reversible)

0. **Vendor + baseline.** Unzip into `frontend/`, `npm install --legacy-peer-deps`, run lint / vitest / build / Playwright once and record the baseline. Add `gateway` to `ALLOWED` in `tests/test_architecture.py` (may import anything, like `council`); add `fastapi`, `uvicorn` to `pyproject.toml`. These two small edits are the only changes outside new directories.
1. **Contract kit.** `gateway/models.py` (pydantic mirrors of the TS types, camelCase) + JSON Schemas; cross-language checks: TS fixtures validate against the Python models, gateway sample output passes the TS `assertWorkspaceSnapshot`.
2. **Gateway skeleton with a scripted fake run** (no engine): projection, event log, SSE with replay, snapshot, commands, CORS, error mapping. Point the frontend at it and make the existing contract suite and e2e pass. De-risks the transport first.
3. **Meeting integration.** `GatewayReporter(Reporter)`: stages → phase/meet events, `say/publish` → messages, `roster` → agents/skills, `ask` → SME question cards, documents → artifacts.
4. **Team integration.** Engine events → events; `AgileState` → sprints/meets/messages; agents, edges, metrics; approvals bridge (`approval-requested` → SME card, answer → `desk.answer`); first-documents approval ↔ `prd.accept`.
5. **Human controls.** Directives (interrupt/say/release), notes, `debate.inject`, `consensus.force`, `agent.task.reassign`, stop run.
6. **Frontend edits** from the list above, with vitest + Playwright updates.
7. **Run & package.** `python -m gateway` (serves the built frontend from `/` or run the Vite dev server), run persistence/resume, token auth, README, one-command start.
8. **End-to-end.** Scripted-LLM full run through the UI in CI, then a live Gemini run by hand.

## Critical files

- New: `gateway/{__main__,app,models,projection,runner,commands,questions,config}.py`, `gateway/translate/*.py`, `tests/gateway/*`, `frontend/**`.
- Edited outside new dirs (only these): `pyproject.toml` (deps, script), `tests/test_architecture.py` (register `gateway`).
- Reused as-is: `meetings/meeting.py` (`run_meeting`, `Reporter`, `meeting_dir`), `meetings/models.py` (`MeetingInput`, `Roster`, `Spec`), `team/engine.py` (`TeamEngine`, `TeamConfig`, `render_report`), `team/agile/{ceremonies.AgileConfig,desk.HumanDesk,model.AgileState,reports}`, `team/cli.py` (`config_from_args` for defaults), `team/events.py` (`describe`), `council_a2a/network.py` (audit entries).
- Frontend: `src/domain/{types,commands,reducers}.ts`, `src/repositories/*`, `src/views/GenUIView/GenUIView.tsx`, `src/components/phases/{PRD,Build,Review,Ship}Phase.tsx`, `src/state/WorkspaceProvider.tsx`.

## Verification

- **Backend untouched:** `git diff <baseline> --stat -- harness meetings team memory council_a2a council` is empty; the full existing suite (≈600 tests) still passes.
- **Gateway tests** (`tests/gateway`, httpx ASGI client + the existing scripted `TeamLLM`/meeting fakes): snapshot validates against the TS rules; SSE versions monotonic, ids unique, replay idempotent; each command's effect and error code; a full scripted run produces the phase sequence kickoff → brainstorm → prd → build → review → ship; the first documents are never accepted without `prd.accept`; restart rebuilds the same snapshot.
- **Frontend:** lint, vitest (mock and http fixtures), build, Playwright against the gateway started with the scripted LLM.
- **Manual:** run `python -m gateway` and the Vite app, submit a brief, answer the SME question, read and accept the documents in the PRD view, watch sprints, standups and the delegation graph, interrupt with a directive, reach Ship; then repeat with real Gemini.

## Risks and how they are handled

- **Snapshot growth** (long transcripts): messages beyond a cap (≈500 most recent) are archived to disk and served by a paged extension later; the contract allows no pagination today, so the cap keeps full-snapshot loads small.
- **Backend event shapes change:** all translation lives in `gateway/translate/`, pinned by tests that fail loudly.
- **UI phase expectations vs automatic backend phases:** backend is the single source of truth; UI buttons become requests.
- **No data for some widgets** (confidence score, per-meet clocks): left to the UI defaults, listed in the README rather than faked.
- **Single process / single run:** one active run per workspace; a second `sprint.start` returns 409.
