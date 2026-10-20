# Running the team from the web UI

The terminal version (`python -m council run`, the TUI) is unchanged. The web UI is a second way to drive the same backend, through the `gateway/` package.

## Start it

```bash
# 1. the gateway (needs GEMINI_API_KEY in .env, like the CLI)
.venv\Scripts\python.exe -m gateway --port 8000 --repo https://github.com/<you>/<repo>

# 2. the UI
cd frontend/agentic-scrum-control-plane
npm install --legacy-peer-deps
cp .env.example .env     # then set the three values below
npm run dev
```

`frontend/agentic-scrum-control-plane/.env`:

```
VITE_TRANSPORT=http-sse
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_WORKSPACE_ID=workspace-demo
```

Open the Vite URL, type a project name and brief, and press **Start the meet**.

To serve the built UI from the gateway itself: `npm run build`, then `python -m gateway --static frontend/agentic-scrum-control-plane/dist`.

Useful gateway flags: `--workspace`, `--output`, `--data`, `--token` (required if `--host` is not local), `--no-a2a`, `--no-memory`.

## What you do in the UI

1. Answer the meeting's product questions (cards in the transcript).
2. Read PRD / Technical Approach / Design. Nothing is built until you press **Accept all documents** (or **Request changes**).
3. During the build, decisions the team needs (design changes, approvals) appear under **Decisions waiting for you**, in both views. Directives and notes go through the Control Plane.
4. The run ends on `final/<run>`. Nothing is merged into `main`; you do that yourself.

## What GitHub sees (when you give a repository)

The team works like a person would, and GitHub follows along:

- Nothing is pushed before you accept the documents (a draft is not published).
- After you accept them, the integration branch (with the signed-off documents) is pushed first, and then **every branch is pushed as it is created and as it grows**: `feature/...` branches, the integration branch after each merge, repair branches, and `final/<run>` at the end.
- Each feature gets a **pull request into the integration branch** when it is first pushed (needs the GitHub CLI signed in as the same account). GitHub shows it as merged once the integrator's merge is pushed.
- `main` is never pushed to. You review `final/<run>` and merge it yourself.
- If GitHub cannot be reached, the build goes on: the failure is shown in the transcript and the terminal, and the end-of-run publish tries again. After three failures live pushing stops for that run.
- The finished page says where the branches went, or that nothing was pushed (no repository, or the push failed).
- Switches for the terminal version: `--no-live-publish` (push only at the end), `--no-feature-prs`, `--final-only`, `--no-publish`.

## Watching a run

- **Terminal:** the gateway prints what the team does and what it is waiting for (`WAITING FOR YOU ...`), with a heartbeat every 20 seconds. `--verbose` adds every developer tool call. The same is kept in `.gateway/gateway.log`.
- **Browser:** click an agent (on the build screen, or in the Control Plane's roster) to see its **live terminal**: the commands it runs, the files it reads and writes, failures, and what it says.
- **Line endings:** a Windows checkout (CRLF) is not treated as a change to every file; the team's first commit contains only your real uncommitted edits.

## Memory: what the team knows, and what each agent knows

Two kinds of memory, both graphs, both searched the same way:

- **Project memory** is shared. Every agent writes to it and reads from it before starting work. It holds the code structure (which file imports which, read from the code itself), what each task did, design decisions, conventions, APIs, pitfalls, and insights.
- **Agent memory** is one private graph per agent: its own tasks, the files it touched, what it struggled with, its habits and preferences. Only that agent reads it.

**Writing.** After each task, merge, design decision, conflict and sprint retrospective, a model extracts atomic memories (a kind, a sentence or two, an importance from 1 to 10, tags, links), then decides for each one: add it, update an existing memory, *supersede* a fact that is no longer true (the old one keeps a validity window), or ignore it because the team already knows it. After each sprint it reflects and writes higher-level insights linked to their evidence. Agents can also write with the `remember` tool and read with `recall`.

**Reading.** A question is rewritten into several searches and an imagined answer (HyDE). Three retrievers run: BM25 (exact words, identifiers, paths), dense vectors (same meaning, different words) and entity linking. Their ranks are fused (reciprocal rank fusion), then Personalized PageRank follows the links from the best hits so connected memories surface, recency and importance are weighted in, and a model reranks the top candidates. Every hit records why it was found. Each task starts with what the project and that agent already know about it.

**Seeing it.** In the Control Plane, the **Memory** tab shows the project graph, each agent's own graph, a list view, details with every link, and a search that shows why each result ranked where it did. Replaced facts are marked. By default the graph shows knowledge, with a code file only when something is linked to it ("Show every file" shows all).

If the model service is overloaded, memory tries other models in turn and then falls back to words and the graph, so it never slows or stops a build. Embeddings use `gemini-embedding-001`.

Files: `memory/graph.py` (storage), `memory/retrieval.py` (search), `memory/extract.py` (writing), `memory/team.py` (the two tiers). Each run keeps its memory under `<output>/<project>/team/memory/` and a readable copy in `team_memory.md`. Switch off with `TeamConfig(team_memory=False)`.

## Long conversations

A developer's conversation is compacted automatically (a checkpoint replaces the older part, the most recent part is kept word for word). The trigger is a working window of 150,000 tokens (`TeamConfig.context_window`), not the model's own 1M-token window, which would never fill.

## Not backed by the backend

`confidenceScore` and per-meet clocks have no source in the backend and use UI defaults. Adding or removing agents/skills in Settings is local to the screen.

## Tests

- `pytest tests/gateway` (contract and end-to-end over HTTP, scripted models)
- `npm run test` in the frontend (mock and live-mode screens)
- `npm run test:e2e:live` (real browser + real gateway + scripted models, about 1.5 minutes)
