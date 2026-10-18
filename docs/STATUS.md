# Harness status (opencode port + team engine)

IDs match the original analysis table. Tests: 348 passing, 1 skipped.

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
| — | Session service (create, prompt, run, wake, interrupt) |
| — | Module boundaries enforced by `tests/test_architecture.py` |

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

1. `Harness` facade and CLI (wire store, runner, tools, permissions, agents, snapshots, worktrees); switch `team/` off `harness/legacy` (ask before deleting legacy)
2. Smaller: tool-input repair (A11), `/init` and custom commands (C6, D6), run coordinator and inbox (A6), title and summary (A8), session export (A10), reference/scout (C7)
3. Rest of the plugin hook host (H1)

## Dropped by decision

webfetch, websearch, MCP, LSP, formatter, codemode, mcp-resource, NOTICE credit line, other providers, OAuth.

## Not started (our additions)

- X1 A2A over gRPC on `a2a-sdk`, with a channel layer for group chats
- X2 Only-needed-skills staffing
- X3 Planning mode with a task DAG
- X4 Agent mode: per-developer sandbox clones, feature branches, merge queue and conflict talks with the branch owner, integration and final branches, main protected
- X5 Design-change meetings
- X6 Project memory; X7 cross-project memory
- README and docs update
