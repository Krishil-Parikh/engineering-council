"""Shaping shell results for the model (opencode: packages/core/src/shell/result.ts)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

UNAVAILABLE = "Shell command output is no longer available."


@dataclass
class Output:
    output: str
    truncated: bool
    exit: Optional[int] = None
    signal: Optional[str] = None
    timeout: Optional[bool] = None


def output_of(info: Any, capture: Optional[dict]) -> Output:
    """info: ShellInfo; capture: {'output': str, 'truncated': bool} or None."""
    return Output(
        output=capture["output"] if capture else UNAVAILABLE,
        truncated=capture["truncated"] if capture else False,
        exit=info.exit, signal=info.signal, timeout=True if info.status == "timeout" else None,
    )


def notice(o: Output) -> Optional[str]:
    if o.timeout:
        return "Timed out before completion"
    if o.signal is not None:
        return f"Killed by {o.signal}"
    if o.exit is not None and o.exit != 0:
        return f"Exited with code {o.exit}"
    return None


def metadata(o: Output) -> dict[str, Any]:
    out: dict[str, Any] = {"truncated": o.truncated}
    if o.exit is not None:
        out["exit"] = o.exit
    if o.signal is not None:
        out["signal"] = o.signal
    if o.timeout is not None:
        out["timeout"] = o.timeout
    return out


def notification(shell_id: str, command: str, state: str, text: str, job_id: Optional[str] = None, output: Optional[Output] = None) -> dict[str, Any]:
    meta: dict[str, Any] = {"source": "shell", "shellID": shell_id}
    if job_id is not None:
        meta["jobID"] = job_id
    meta["state"] = state
    if output:
        meta.update(metadata(output))
    return {"text": f'<shell id="{job_id or shell_id}" state="{state}" command="{command}">\n{text}\n</shell>', "metadata": meta}


def user_notification(info: Any, capture: Optional[dict]) -> dict[str, Any]:
    captured = output_of(info, capture)
    if info.status == "killed":
        status: Optional[str] = "Cancelled"
    elif captured.exit == 0:
        status = None
    else:
        status = notice(captured) or "Exited with code unknown"
    msg = notification(info.id, info.command, "cancelled" if info.status == "killed" else "completed",
                       "\n\n".join(t for t in (captured.output, status) if t), output=captured)
    return {**msg, "text": f"The following shell command was executed by the user:\n{msg['text']}"}
