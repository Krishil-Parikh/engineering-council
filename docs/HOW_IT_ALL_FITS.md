# How Engineering Council fits together

An autonomous dev team. You give it a brief and (optionally) a GitHub repo. A pod of AI developers explores the repo, meets, writes a PRD, Technical Approach and Design, you accept them, then they build in sprints and hand you a `final/<run>` branch to merge. The system never pushes `main`.

## The three layers

**Frontend** (`frontend/agentic-scrum-control-plane`)
The control plane you watch and steer from. It never talks to the engine directly; it talks to one interface, `WorkspaceRepository` (snapshot, commands, event stream). In demo mode that is an in-memory mock; in live mode (`npm run dev:live`) it is HTTP + Server-Sent Events.
Screens: kickoff, meeting, documents, build, review, ship, Control Plane (agents, terminals, sprints, memory graphs) and Standup (live and replayable meetings).

**Gateway** (`gateway/`)
A FastAPI server that translates between the frontend's contract and the Python engine. It exposes `GET /workspace/{id}/snapshot`, `POST /commands`, an SSE `/events` stream, and memory/search endpoints. It turns meeting and team events into UI events, keeps live terminals per agent, and logs to the terminal and `gateway.log`.

**Backend** (Python packages)
- `meetings/` – the pod meeting: repo exploration, blind thinking, skill picking, debate, product questions for you, documents, verification.
- `team/` – the build: agile sprints, parallel developers in their own git sandboxes and branches, merges, checkpoint commits, live push to GitHub with a PR per feature.
- `harness/` – our own coding agent engine (sessions, tools, permissions, automatic compaction), ported from opencode.
- `memory/` – graph memory: one shared project graph and one private graph per agent.
- `standup/` – formal meetings as a replayable event stream; the Standup tab shows them live (optional autopilot Business SME).
- `council_a2a/` – Agent2Agent protocol over gRPC; every agent-to-agent message goes through it.
- `council/` – the CLI/TUI entry point (`python -m council run`).
`tests/test_architecture.py` enforces who may import whom.

## Memory

A SQLite graph of files, tasks, decisions, conventions, pitfalls and insights. Retrieval is hybrid: BM25 keywords + Gemini embeddings + entity linking, fused, then PageRank over the graph, then recency/importance weighting and an optional LLM rerank. It starts at kickoff, when the pod reads the repo.

## Tech stack

| Area | Used |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, React Flow (`@xyflow/react`), Recharts, Framer Motion, Lucide |
| Frontend tests | Vitest, Testing Library, Playwright (demo and live end-to-end) |
| Gateway | FastAPI, Uvicorn, Pydantic, SSE |
| Backend | Python 3.11+, asyncio, Pydantic, Textual (TUI), tree-sitter (shell parsing), PyYAML |
| Agent protocol | a2a-sdk over gRPC |
| Model | Google Gemini (`google-genai`), chat and `gemini-embedding-001` |
| Storage | SQLite (sessions, memory graphs), plain files for meeting output |
| Git | real git repositories, branches, merges; GitHub CLI (`gh`) for pushes and PRs |
| Python tests | pytest |

## Run it

```
.venv\Scripts\python.exe -m gateway --port 8000 --fresh
cd frontend\agentic-scrum-control-plane && npm run dev:live
```
Needs `GEMINI_API_KEY` in `.env` and `gh` logged in as the repo's owner.
