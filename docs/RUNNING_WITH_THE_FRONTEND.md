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

## Not backed by the backend

`confidenceScore` and per-meet clocks have no source in the backend and use UI defaults. Adding or removing agents/skills in Settings is local to the screen.

## Tests

- `pytest tests/gateway` (contract and end-to-end over HTTP, scripted models)
- `npm run test` in the frontend (mock and live-mode screens)
- `npm run test:e2e:live` (real browser + real gateway + scripted models, about 1.5 minutes)
