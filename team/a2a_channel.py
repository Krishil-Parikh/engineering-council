"""The team's conversations over A2A (gRPC).

Every developer (and the integrator) is an A2A agent on a local network. A question to a teammate is an A2A `SendMessage` to that agent's
gRPC server; the agent's handler runs the consultation on the developer's own harness, exactly as the in-process channel does, and the
answer comes back as an A2A Message. Every exchange is written to an audit log, and the agents only accept callers that present the
network's token."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from council_a2a import A2ANetwork, Inbound
from team.channel import LocalChannel

if TYPE_CHECKING:
    from team.engine import TeamEngine


async def open_network(engine: "TeamEngine", audit_path: Path) -> A2ANetwork:
    consult = LocalChannel(engine.harness, lambda d: engine.roster.get(d, "INTEGRATOR"))
    network = A2ANetwork(token=secrets.token_hex(16), audit_path=audit_path)

    def handler_for(name: str):
        async def handle(inbound: Inbound) -> str:
            return await consult.ask(inbound.sender, name, inbound.text, inbound.topic)

        return handle

    for name in [*engine.developers, "integrator"]:
        skill = engine.roster.get(name, "INTEGRATOR")
        await network.add(name, handler_for(name), f"{name}, {skill.title()} developer" if name in engine.roster else "Integrator: merges the team's work", skill)
    return network
