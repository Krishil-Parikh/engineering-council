# Harness status (opencode port + team engine)

IDs match the original analysis table. Tests: 447 passing, 1 skipped.

## Done

| # | Item |
|---|---|
| A1, A2 | SQLite session store; typed message model with tool state machine |
| A3, A4, A5 | Step loop and outcomes; retry policy; max-steps wrap-up |
| B1–B8 | Compaction: estimate, ceiling, split, summary prompts, nudge, 70/50/35% shrink loop, flatten and drop oldest, checkpoint rendering |
| C1–C5 | Instruction discovery, instruction state, built-in context, nearby `AGENTS.md`, skill discovery |
| D1 | Agent registry (build, general, explore, plan, compaction, title, summary; config agents) |
| D3, D4 | Permission engine; external-directory approval |
| D5 | Config discovery and loading |
| E1–E3 | `read`, `edit`, `write`, `patch`, `glob`, `grep` |
| E4 | `shell` (tree-sitter scanning, process service, jobs, background notifications) |
| E5 | Output truncation to files |
| E9 | `subagent` (child sessions, depth limit, background, completion notification, model override) |
| E8 | `question` and the form service |
| E10 | `skill` tool |
| F1, F2, F3 | Git service (clone, fetch, worktrees, snapshot store), snapshots (capture, files, diff, restore), worktree manager |
| — | `harness_*` tools: session rename/move, worktree create/list/remove, models |
| G1, G2 | Gemini provider (verified live); model catalog |
| — | Session service (create, prompt, run, wake, interrupt); `Harness` facade (`harness/app.py`) wiring everything per working directory; checked live against Gemini (write, shell, subagent, grep, edit) |
| — | Module boundaries enforced by `tests/test_architecture.py` |
| X1 | A2A over gRPC on the official `a2a-sdk` (`council_a2a`): agent servers, clients, token auth, audit log, direct/broadcast/group conversations; the team's conversations use it |
| X3, X4 | Team engine (`team/`): plan as a feature graph, scheduler, per-developer sandbox clones, feature branches, merge queue with conflict talks, protected main, final branch, resume; checked live against Gemini |
| X2 | Staffing by need: developers name the skills the problem needs, only those get seats, several developers can share a skill |
| X3 | Planning is a team discussion (one group conversation over A2A) before the scrum master writes the plan |
| X1 | The meeting's own developer calls also travel over A2A (`--no-a2a` to turn off) |
| X5 | Design-change meetings with votes and ADRs |
| X6 | Project memory (`memory/project.py`): code map regenerated after every merge, project log compacted into a checkpoint, both committed in the repo and shown to developers per task |
| X7 | Cross-project memory (`memory/lessons.py`, `learn.py`): lessons learned from conflicts, failures, verification and design changes; recall into planning and tasks; developer experience profiles; lessons seen on two projects promoted to skills the harness loads |

## Partial

- A7: token and cost accounting only, no stats
- B9, B10: failure events, plugin hook and per-agent compaction model not confirmed
- D2: plan-mode reminders
- E12: locking and diffs yes, stale-file guard no
- E13: registry has add and snapshot, no override/disable
- H1: only the `context_hooks` hook exists
- E4: PowerShell is scanned with a simple splitter, not a grammar
- A9: snapshots can restore files, but there is no revert/undo command on a session yet

## Left in the harness

1. `python -m harness` CLI; switch `team/` off `harness/legacy` (ask before deleting legacy)
2. Smaller: tool-input repair (A11), `/init` and custom commands (C6, D6), run coordinator and inbox (A6), title and summary (A8), session export (A10), reference/scout (C7)
3. Rest of the plugin hook host (H1)

## Dropped by decision

webfetch, websearch, MCP, LSP, formatter, codemode, mcp-resource, NOTICE credit line, other providers, OAuth.

## Not started (our additions)


- README and docs update
