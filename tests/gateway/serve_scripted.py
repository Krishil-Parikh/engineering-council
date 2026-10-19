"""Runs the gateway with scripted models on a fixed port, for the browser test (frontend/.../e2e-live). Not part of the product.

    python tests/gateway/serve_scripted.py [port]
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from gateway.app import create_app  # noqa: E402
from gateway.config import GatewaySettings  # noqa: E402
from tests.gateway.conftest import make_deps  # noqa: E402


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    work = Path(tempfile.mkdtemp(prefix="gateway-e2e-"))
    settings = GatewaySettings(
        port=port, output_dir=work / "output", data_dir=work / "data", a2a=False, memory=False, repair_rounds=0, workspace_id="workspace-demo",
        cors_origins=("http://127.0.0.1:3100", "http://localhost:3100"),
    )
    print(f"scripted gateway on http://127.0.0.1:{port} (work folder {work})", flush=True)
    uvicorn.run(create_app(settings, make_deps()), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
