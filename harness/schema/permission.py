"""Permission types (opencode: packages/schema/src/permission.ts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

Effect = Literal["allow", "deny", "ask"]
Reply = Literal["once", "always", "reject"]


@dataclass(frozen=True)
class Rule:
    action: str
    resource: str
    effect: Effect


Ruleset = list[Rule]


@dataclass
class Request:
    """A pending question to the user: may `action` be done on `resources`?"""

    id: str
    session_id: str
    action: str
    resources: list[str]
    save: Optional[list[str]] = None  # what "always" remembers (patterns), if different from the resources
    metadata: dict[str, Any] = field(default_factory=dict)
    source: Optional[dict[str, Any]] = None
    message: Optional[str] = None
