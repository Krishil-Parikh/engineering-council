# How Engineering Council fits together

An autonomous dev team. You give it a brief and (optionally) a GitHub repo. A pod of AI developers explores the repo, meets, writes a PRD, Technical Approach and Design, you accept them, then they build in sprints and hand you a `final/<run>` branch to merge. The system never pushes `main`.

## The three layers

**Frontend** (`frontend/agentic-scrum-control-plane`)
The control plane you watch and steer from. It never talks to the engine directly; it talks to one interface, `WorkspaceRepository` (snapshot, commands, event stream). In demo mode that is an in-memory mock; in live mode (`npm run dev:live`) it is HTTP + Server-Sent Events.
Screens: kickoff, meeting, document review, build, review, ship, a Control Plane dashboard (agents, live terminals, sprints) and a Memory tab drawing the memory graphs.

**Gateway** (`gateway/`)
A FastAPI server that translates between the frontend's contract and the Python engine. It exposes `GET /workspace/{id}/snapshot`, `POST /commands`, an SSE `/events` stream, and memory/search endpoints. It runs one workspace at a time, turns meeting and team events into UI events, keeps live terminals per agent, and logs everything to the terminal and `gateway.log`.

**Backend** (Python packages)
- `meetings/` – the pod meeting: repo exploration, blind thinking, skill picking, debate, product questions for you, documents, verification.
- `team/` – the build: agile sprints, parallel developers in their own git sandboxes and branches, merges, checkpoint commits, live push to GitHub with a PR per feature.
- `harness/` – our own coding agent engine (sessions, tools, permissions, automatic compaction), ported from opencode.
- `memory/` – graph memory: one shared project graph and one private graph per agent.
- `council_a2a/` – Agent2Agent protocol over gRPC; every agent-to-agent message goes through it.
- `council/` – the CLI/TUI entry point (`python -m council run`).
`tests/test_architecture.py` enforces who may import whom.

## Memory

Stored in SQLite. Nodes (files, tasks, decisions, conventions, pitfalls, insights) and edges. Retrieval is hybrid: BM25 keywords + Gemini embeddings + entity linking, fused with reciprocal rank fusion, then Personalized PageRank over the graph, then recency/importance weighting and an optional LLM rerank. Memory starts at kickoff, when the pod reads the repo, and grows with every task, decision and merge.

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
