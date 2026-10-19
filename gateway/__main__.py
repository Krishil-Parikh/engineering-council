"""`python -m gateway`: serve the frontend's backend contract.

    python -m gateway                              the API on http://127.0.0.1:8000 (run the frontend with `npm run dev`, VITE_TRANSPORT=http-sse)
    python -m gateway --static frontend/agentic-scrum-control-plane/dist     also serve the built frontend, one process, one address

The terminal interface (`python -m council run`) is unchanged and can be used at any time; both write to the same output folder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gateway.config import GatewaySettings


def main(argv: list[str] | None = None) -> int:
    base = GatewaySettings.from_env()
    p = argparse.ArgumentParser(prog="python -m gateway", description="The web API the frontend talks to.")
    p.add_argument("--host", default=base.host)
    p.add_argument("--port", type=int, default=base.port)
    p.add_argument("--workspace", default=base.workspace_id, help="the workspace id the frontend loads (its VITE_WORKSPACE_ID)")
    p.add_argument("--output", default=str(base.output_dir), help="where meetings and builds go (the same folder the terminal uses)")
    p.add_argument("--data", default=str(base.data_dir), help="where the gateway keeps its event log")
    p.add_argument("--static", default=str(base.static_dir) if base.static_dir else None, help="the built frontend to serve at / (frontend/.../dist)")
    p.add_argument("--repo", default=base.repo, help="a repository to build on and publish to when a brief does not name one")
    p.add_argument("--token", default=base.token, help="require this token on every request (Bearer header, or ?token= for the event stream)")
    p.add_argument("--no-a2a", action="store_true", help="call the model in-process instead of over A2A (not recommended)")
    p.add_argument("--no-memory", action="store_true", help="neither use nor update cross-project memory")
    args = p.parse_args(argv)
    settings = GatewaySettings(
        host=args.host, port=args.port, workspace_id=args.workspace, output_dir=Path(args.output), data_dir=Path(args.data), token=args.token,
        cors_origins=base.cors_origins, static_dir=Path(args.static) if args.static else None, repo=args.repo, a2a=not args.no_a2a, memory=not args.no_memory,
    )
    if settings.host not in ("127.0.0.1", "localhost", "::1") and not settings.token:
        print("Refusing to listen on a public address without --token: anyone who can reach it could start runs on your API key.", file=sys.stderr)
        return 1
    import uvicorn

    from gateway.app import create_app

    where = f"http://{settings.host}:{settings.port}"
    print(f"Gateway on {where}  (workspace {settings.workspace_id}; output {settings.output_dir.resolve()})")
    if settings.static_dir is not None:
        print(f"Frontend: {where}/")
    else:
        print("Frontend: run `npm run dev` in frontend/agentic-scrum-control-plane with VITE_TRANSPORT=http-sse and VITE_API_BASE_URL=" + where)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
