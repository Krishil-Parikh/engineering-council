# Status: harness (opencode port), team engine, agile playbook

Everything below is built and covered by offline tests (no network, scripted model). The first real-model run (Habitly, Gemini 3.6 Flash,
6 features, 2 sprints, about $0.08) completed and was reviewed; see "Lessons from the first real run" below.

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

## Lessons from the first real run (Habitly)

The run finished with every feature merged and verification passing, but a review of the code it produced scored it **6/10**. The sprint
process worked (planning, standups, review, retrospective, document sync, all in `docs/agile/`). The weaknesses were in what the pipeline
did not check:

- no `habitly` command existed (no console script), and `python -m habitly` failed, although the spec required `habitly <command>`;
- the dashboard's weekly report was always empty: the JavaScript read `habits` / `habit_name` / `completion_rate`, the API returned
  `habit_summaries` / `name` / `rate` (two agents, two sides of one contract, no test between them);
- the API crashed on a fresh database when started without the CLI; CSV export broke on a quote in a name; the project README was 3 lines
  although the spec required install, commands, endpoints and test instructions; build junk (`*.egg-info`) was committed; 81 lint findings.

The run passed because its only verification command was `python -m pytest -q`, which tests units, not the spec's "done means".

## Planned improvements (in this order)

1. **Acceptance step at the end of every sprint and before the final branch.** The scrum master turns the specification's "done means" list
   into runnable checks (each named command is executed and its output compared with what the spec says), plus a README check (the sections the
   spec asked for exist and are not a stub). Failures become a repair task for the right developer, exactly like failed verification does today,
   and are shown in the sprint review and report.
2. **Contract tests whenever two features meet.** When a feature depends on or consumes another's output (a dashboard and an API, a CLI and a
   service), planning adds an integration task owned by the consumer: a test that starts the real producer and checks the real payload shape.
   The integration branch cannot be finalized while such a test is missing or failing.
3. **Quality gate before merge into the integration branch.** Run the project's linter and type checker if the project has them (and, if it
   has none, add a minimal config as part of the first feature); refuse files that should not be committed (build output, `*.egg-info`,
   caches) and add them to `.gitignore`.
4. **Packaging check.** If the spec names a command (`habitly add ...`), verify that installing the project makes that command exist
   (console script entry point) and that `python -m <package>` works.
5. **Review pass by a developer who did not write the code.** After each feature, a different developer reviews the diff for the classes of
   bug found above (unescaped output, ambiguous identifiers, missing validation, N+1 queries, duplicated logic) and files findings as tasks.
6. **Publish prompt.** When the run was not started with `--publish` and a target repository exists (for example on the start form), ask at
   the end whether to push `final/<run>` there, instead of leaving the work only on disk. (In the Habitly run nothing reached GitHub because the
   run was started without `--publish`; the branches were pushed by hand afterwards.)

## Not done

- A second real-model run to confirm the planned improvements catch what the first run missed (re-run Habitly and compare).
- A web front end (the desk, the gate and the playbook are plain objects with async methods, ready for one to call). The integration plan is in
  `docs/FRONTEND_INTEGRATION_PLAN.md`.
