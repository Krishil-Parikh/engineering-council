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
    return _agile(kind, d)


def _agile(kind: str, d: dict) -> Optional[tuple[str, str]]:
    """The sprint process: planning, work days, standups, review, report, retrospective, document sync, and the human's part in it."""
    if kind == "sprint-planned":
        carried = f"\n   carried over: {', '.join(d['carried'])}" if d.get("carried") else ""
        return "info", f"\n== SPRINT {d['sprint']} PLANNED ==  {d['tasks']} task(s), {len(d['features'])} feature(s)\n   goal: {_short(d['goal'], 200)}" + carried
    if kind == "day-start":
        return "dim", f"-- sprint {d['sprint']}, day {d['day']}: {', '.join(d['working']) or 'nobody'} working"
    if kind == "gate-freeze":
        return "dim", f"   coding paused ({d['holder']})"
    if kind == "gate-thaw":
        return "dim", f"   coding may resume ({d['holder']} done)"
    if kind == "standup":
        return "info", f"[standup {d['number']}] day {d['day']}: {_short(d['summary'], 220)}"
    if kind == "impediment":
        return "warn", f"[impediment] {d['id']} ({d['dev']}): {_short(d['text'], 160)}"
    if kind == "sprint-review":
        return ("ok" if d["goal_met"] else "warn"), f"[review]  sprint {d['sprint']}: goal {'met' if d['goal_met'] else 'NOT met'}. {_short(d['summary'], 200)}"
    if kind == "sprint-report":
        return "info", f"[report]  sprint {d['sprint']}: {d['completed']}/{d['planned']} tasks delivered"
    if kind == "sprint-retro":
        return "info", f"[retro]   sprint {d['sprint']} actions: {_short('; '.join(d['actions']), 200) or 'none'}"
    if kind == "doc-sync":
        return "info", f"[docs]    sprint {d['sprint']}: {len(d['applied'])} of {d['proposed']} proposed amendment(s) applied"
    if kind == "agile-docs":
        return "dim", f"[docs]    {d['message']} ({len(d['files'])} file(s))"
    if kind == "feature-dropped":
        return "warn", f"[dropped] {d['feature']}: {_short(d['detail'], 120)}"
    if kind == "feature-requeued":
        return "warn", f"[retry]   {d['feature']} goes back into a sprint"
    if kind == "approval-requested":
        return "warn", f"[needs you] {d['title']}"
    if kind == "approval-answered":
        return ("ok" if d["approved"] else "warn"), f"[decision] {d['title']}: {'approved' if d['approved'] else 'declined'}"
    if kind == "interrupted":
        return "warn", "[you] the team is paused" + (f" (still finishing a step: {', '.join(d['late'])})" if d.get("late") else "")
    if kind == "directive-handled":
        return "info", f"[you] {d['kind']}: {_short(d['effect'], 200)}"
    if kind == "resumed":
        return "ok", "[you] work resumes"
    if kind == "note":
        return "info", f"[you] note for the next standup: {_short(d['text'], 160)}"
    if kind == "agile-warning":
        return "warn", f"[agile]   {_short(d['text'], 200)}"
    return None


def describe_talk(d: dict) -> tuple[str, str]:
    """A conversation between two members: the question and the start of the answer."""
    head = f"{d['sender']} -> {d['recipient']}" + (f"  [{_short(d['topic'], 60)}]" if d.get("topic") else "")
    reply = f"\n    {_short(d['reply'], 220)}" if d.get("reply") else ""
    return "info", f"{head}\n    {_short(d.get('text', ''), 220)}{reply}"
