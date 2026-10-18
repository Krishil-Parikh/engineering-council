# Status: harness (opencode port), team engine, agile playbook

Everything below is built and covered by offline tests (no network, scripted model). The real-model proof of concept (a full run against
Gemini covering conflicts, a design vote, memory recall and a git failure) is the one thing left to do.

## The pipeline

`python -m council run` takes a prompt through: kickoff meeting and Q&A, the human accepting the documents, then sprints (planning, work
days, standups, review, report, retrospective, document sync), leaving `final/<run>` for the human to merge. The human can interrupt at any
time in the full-screen view; every major decision waits for them. All agent conversations travel over A2A.

| Area | What exists |
|---|---|
| Sprint playbook (`team/agile/`) | work gate that freezes coding between steps during every ceremony; day = a task or a step budget; sprint planning from the backlog by capacity and measured velocity; standups from real facts (task log, git) with impediments and resolutions; review (verification on the integration branch, demos); sprint report (planned vs delivered, burndown, velocity); retrospective (actions become working agreements and a long-term lesson); document sync (routine edits applied and logged, major ones need the human); failed features retried once, unfinished ones carried over; state saved so a stopped run resumes |
| Documents written to `docs/agile/` | `product_backlog.md`, `velocity.md`, `impediments.md`, `human_directives.md`, `CHANGELOG.md`; per sprint: `sprint_backlog.md`, `standups/standup-NN.md`, `review.md`, `sprint_report.md`, `retrospective.md` |
| The human's desk | the first documents are never accepted automatically (read in full, approve or send back with feedback; revised and asked again); design changes the team voted for, PRD amendments and course corrections wait for a yes; interrupt (`i`) to speak: notes, change of scope (emergency replanning: drop a running feature, add, reorder), stop-and-rethink; notes for the next standup (`n`); decisions waiting (`p`) |
| Team engine | feature-graph plan, scheduler, per-developer sandbox clones, protected main, merge queue, conflict talks, design votes with ADRs, git brain that diagnoses and fixes failed git steps, publish and pull request, resume, project and cross-project memory, shared model throttle |
| A2A | official `a2a-sdk` over gRPC: agent servers, clients, token auth, audit log, direct/broadcast/group conversations; planning, standups, votes, conflict talks and briefings to developers all use it |
| Entry points | `python -m council run | build | resume | revise`, `python -m harness` |

## The coding harness (port of opencode's logic)

| Item | |
|---|---|
| Sessions | SQLite store, typed messages with a tool state machine, step loop, retry policy, max-steps wrap-up, run coordinator (one run per session), inbox (steer, queue, manual compaction), titles, revert (stage, undo, commit), stats, export and import |
| Compaction | estimate, ceiling, split, summary prompts, nudge, shrink loop, checkpoint; events and hooks; optional separate model |
| Memory | instruction discovery and state, nearby `AGENTS.md`, skills, project memory, cross-project lessons |
| Agents | build, plan (read-only, reminder through the hook host), general, explore, scout (reference repositories), compaction, title, summary; configured agents |
| Tools | read, edit, write, patch, glob, grep, shell (tree-sitter bash and PowerShell), subagent (child sessions, background), question, skill, reference, harness_* tools; input repair; output truncation; stale-file guard; override and disable |
| Safety | permission engine (last matching rule wins), external-directory approval, snapshots and worktrees |
| Extensibility | hook host (`context`, `tool.before`, `tool.after`, `input`, `event`, `compaction.request`, `compaction.summary`), plugins from `plugins/*.py` or configuration |
| Commands | slash commands (`/init`, `/review`, config and markdown commands) |
| Providers | Gemini (verified live), model catalog |

## Dropped by decision

webfetch, websearch, MCP, LSP, formatter, codemode, mcp-resource, NOTICE credit line, other providers, OAuth. The first, smaller port of the
harness (`harness/legacy`) and the old sequential build runner were removed once everything moved to the new harness.

## Not done

- The real-model run described above.
- A web front end (the desk, the gate and the playbook are plain objects with async methods, ready for one to call).
