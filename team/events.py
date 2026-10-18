"""What the engine reports while it works, in words. One place, so the plain output and the full-screen view say the same thing.

`describe(kind, data)` returns (style, text) for an event worth showing, or None for events that are only for programs. Styles are plain names:
info, ok, warn, bad, dim."""

from __future__ import annotations

from typing import Optional


def _short(text: str, n: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def describe(kind: str, d: dict) -> Optional[tuple[str, str]]:
    if kind == "seeded":
        return "info", f"specification and project memory committed to {d['branch']}"
    if kind == "plan":
        lines = ["work plan"]
        for f in d["plan"]["features"]:
            after = f" (after {', '.join(f['depends_on'])})" if f["depends_on"] else ""
            lines.append(f"  {f['id']} -> {f['owner']}{after}: {f['title']}")
        return "info", "\n".join(lines)
    if kind == "plan-discussion":
        return "info", f"the team talked the plan through ({len(d['speakers'])} contributions)"
    if kind == "feature-started":
        return "info", f"[start]   {d['feature']} ({d['owner']})"
    if kind == "feature-done":
        return "ok", f"[merged]  {d['feature']}: {d['detail']}"
    if kind == "feature-failed":
        return "bad", f"[FAILED]  {d['feature']}: {d['detail']}"
    if kind == "feature-blocked":
        return "warn", f"[blocked] {d['feature']}: {d['detail']}"
    if kind == "task":
        return "dim", f"          task {d['index']}/{d['total']} ({d['owner']}): {d['title']}"
    if kind == "conflict":
        return "warn", f"[conflict] {d['feature']}: {', '.join(d['files'])}"
    if kind == "conflict-talk":
        return "warn", f"           talking with {', '.join(d['with_'])} (round {d['round']})"
    if kind == "design-followup":
        return "info", f"[design]  {d['owner']} is updating docs/Design.md for {', '.join(d['adrs'])}"
    if kind == "git-trouble":
        return "warn", f"[git]     {d['dev']}: {d['goal']} failed (attempt {d['attempt']}): {_short(d['error'])}"
    if kind == "git-fixed":
        return "ok", f"[git]     {d['dev']}: fixed ({_short(d.get('how', '') if d.get('how') != 'agent' else d.get('note', 'by the agent'))})"
    if kind == "git-unfixed":
        return "warn", f"[git]     {d['dev']}: the agent could not fix it yet, trying again"
    if kind == "git-gave-up":
        return "bad", f"[git]     {d['dev']}: gave up on '{d['goal']}': {_short(d['error'])}"
    if kind == "verification":
        return ("ok" if d["failing"] == 0 else "warn"), f"[verify]  {d['failing']} failing command(s) (attempt {d['attempt'] + 1})"
    if kind == "final":
        return "ok", f"[final]   {d['branch']} is ready for you to review"
    if kind == "published":
        return "ok", f"[publish] {', '.join(d['branches'])} pushed to {d['target']}"
    if kind == "pull-request":
        return "ok", f"[pr]      pull request opened: {d['url']}"
    return None


def describe_talk(d: dict) -> tuple[str, str]:
    """A conversation between two members: the question and the start of the answer."""
    head = f"{d['sender']} -> {d['recipient']}" + (f"  [{_short(d['topic'], 60)}]" if d.get("topic") else "")
    reply = f"\n    {_short(d['reply'], 220)}" if d.get("reply") else ""
    return "info", f"{head}\n    {_short(d.get('text', ''), 220)}{reply}"
