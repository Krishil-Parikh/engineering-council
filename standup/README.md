# Standup

Formal Scrum meetings as a **structured, replayable event stream**, with a live screen for them.

The meeting engine (`meetings/`, `team/`) runs the agents. Standup does not run anything: it records what is *said in the formal meetings*, keeps it, and shows it. The `.txt` transcript is a
projection of the events, never the source of truth.

## Formal meetings only

Recorded: the kickoff (discovery), the document review, sprint planning, daily standups, the sprint review, the retrospective, design votes and the Business SME's checkpoints.
**Never recorded:** tool calls, shell commands, merge talk, a developer's working chatter, the team's general conversation. The gateway decides what is formal in one place:
`gateway/standup_hub.py::classify`. Anything it does not recognise is left out.

## Layout

```
standup/                   imports nothing else from the repository (enforced by tests/test_architecture.py)
  enums.py  errors.py      the vocabulary; structured errors
  events.py                the versioned event contract (SCHEMA_VERSION), payload rules, secret redaction
  models.py  state.py      entities, and the state machine that applies events (same code live and on replay)
  ports.py                 MeetingEventStore, StreamPublisher, MeetingWriter, Clock, IdGenerator: small, separate
  service.py               use cases: create, publish, read, replay, state_at, time out
  transcript.py            the readable transcript, deterministic
  presentation.py          the view model for screens (an Agent Standup style team call) and the timeline translator
  adapters/                memory_store, jsonl_store (events.jsonl), files (transcript.txt + JSON summaries), layout (safe paths), system (clock, ids)
gateway/standup_hub.py     records the run's formal meetings (listens to the workspace event stream), fans out live
gateway/standup_routes.py  REST + resumable SSE
gateway/autopilot.py       the autopilot Business SME
frontend/.../src/views/standup/   the screen: models, adapters (HTTP, demo), hooks, components, tests, fixtures
```

Dependency direction: `gateway` → `standup`; `standup` → nothing. `meetings/` and `team/` do not know it exists.

## Events

Append-only, one monotonic `sequence_number` per meeting (order never depends on timestamps), unique `event_id`, `schema_version`, `correlation_id`, optional `idempotency_key`.
Kinds: see `EventType` (meeting lifecycle, participants, skills and roles, topics, statement / brainstorm / proposal / challenge / counterargument, questions and clarifications, risks,
dependencies, facilitator interventions, human takeover / autopilot, decisions, action items, documents and their review, SME approvals, blocks, summary).

Rules, all enforced in `MeetingState` before anything is stored: an answer needs its question, a decision must be proposed before it is settled, a person must have joined before they speak
or leave, nothing happens before the start or after the end, time never runs backwards. A duplicate is ignored; a gap is refused (`OutOfOrder`); a kind this version does not know (written by a
newer one) is kept and ignored, so an old reader never breaks.

Order of work for each event: **validate → store durably → apply → write projections → publish**. A projection or a watcher that fails is logged and skipped; it can never lose an event.

## Storage

`<gateway data>/<workspace>/standup/<record>/<workspace>/<meeting>/` holds `events.jsonl` (the truth), `transcript.txt`, `decisions.json`, `questions.json`, `action-items.json`,
`participants.json`, `metadata.json`. A new project starts a new `<record>`; old ones stay readable (`?record=`). A half-written last line after a crash is cut off on the next open.
Ids become folder names, so they are checked (`[A-Za-z0-9._-]`, at most 80) and every path is checked to stay inside the root.

## HTTP

```
GET  /workspace/{id}/standup/meetings[?record=]
GET  /workspace/{id}/standup/meetings/{m}[?at=<sequence>&record=]     view of the meeting, now or at a point (the replay scrubber)
GET  /workspace/{id}/standup/meetings/{m}/events?after=&limit=
GET  /workspace/{id}/standup/meetings/{m}/transcript
GET  /workspace/{id}/standup/meetings/{m}/stream?after=               SSE; resumes from Last-Event-ID; heartbeats; says "end" when the meeting is over
POST /workspace/{id}/standup/meetings/{m}/answer    {questionId, answer}
POST /workspace/{id}/standup/meetings/{m}/direct    {text}            interrupt or redirect (travels as a directive)
POST /workspace/{id}/standup/control                {mode: human|autopilot}
```
Every event is also announced on the ordinary workspace stream as `standup.event`. The same bearer-token rules as the rest of the gateway apply.

## Human takeover and the autopilot Business SME

The Business SME answers the team's questions on the screen (or in the Control Plane). **Autopilot** is an option for when nobody is there: it answers the *product questions* the pod asks, in
the voice of the person who owns the brief, with a short pause first so a person can still answer. It records `source: autopilot`. Taking control back (`human_takeover`) stops it at once, even
mid-answer. **It never approves anything:** the first documents and every decision that needs approval wait for a person, in either mode. If the model is unavailable it falls back to the
recommended default; with no default it leaves the question for you.

## Frontend

The Standup tab shows the meetings of the run, the people (any number, with the skill and temporary role they took *for this meeting*), the conversation, questions waiting for the Business SME,
decisions, action items, risks, documents under review and approvals, a replay (play, step, speed, scrubber, jump to decisions / questions / interventions), and the transcript.
It reads the server's view of a meeting (`StandupView`), so no meeting rule is written twice. In demo mode it uses recorded meetings produced by the real service:
`python -m tests.standup.make_fixtures` rewrites them, and a test fails when they drift from the code. Another test reads the TypeScript types and fails when they disagree with the backend models.

## How to

- **A new meeting type:** add it to `MeetingType` and, for the gateway, a line in `CLASSES` (`gateway/standup_hub.py`) and a label in `frontend/.../models/meeting-status.ts`. No store or contract change.
- **A new event kind:** add it to `EventType`, to `REQUIRED` (its fields) and, if it changes state, an `_on_<kind>` method in `state.py`; add it to `MEETING_EVENT_TYPES` in the frontend (a test checks both
  lists) and a line in `transcript.py`. Nothing else changes.
- **A new presentation:** write another function from `MeetingState` to your own view model next to `presentation.py`. The domain does not change.
- **Replay a meeting:** in the Standup tab, "Replay this meeting"; or `GET .../meetings/{m}?at=N`; or in Python `service.state_at(meeting_id, N)`. After a restart the meetings are read back from `events.jsonl`.
- **Run the tests:** `.venv\Scripts\python.exe -m pytest tests/standup tests/gateway/test_standup.py -q` and, in `frontend/agentic-scrum-control-plane`, `npx vitest run src/views/standup`,
  `npx playwright test e2e/standup.spec.ts`, `npx playwright test -c playwright.live.config.ts standup`.

## Security and privacy

A service serves one workspace, so another workspace's meetings cannot be reached through it. Secret-looking text (keys, tokens, private keys, values under keys named like `api_key`) is redacted before
it is stored. Text from people is rendered as text, never markup. No model reasoning is stored: only what was said, decided or asked. Nothing here sends anything outside the gateway.

## Not done yet

The engine does not yet emit these, so the screen only shows them when something else supplies them: per-meeting skill choice and temporary roles (skills are chosen once at kickoff today),
risks and dependencies as events (they appear in standups as plain text), a pause of the real meeting from the screen (the record can be paused; the agents keep working).
