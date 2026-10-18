# Engineering Council CLI

A terminal tool that turns a problem statement into three reviewed, consistent specification documents — `PRD.md`, `Technical_Approach.md` and `Design.md` — by running a conversational pod meeting: six developers who each pick a skill, led by a scrum master. Python + Gemini API only. See [docs/PRD.md](docs/PRD.md) and [docs/Technical_Approach.md](docs/Technical_Approach.md) for the product spec this implements.

## How the meeting works

Six generalist developers (`DEV_1`...`DEV_6`) and a scrum master (the pod lead) hold a real, multi-round conversation.

| # | Stage | What happens |
|---|---|---|
| 1 | Inspect | Optional read-only repository snapshot (secrets excluded and redacted, nothing executed). |
| 2 | Blind thinking | Each developer reads the problem alone **with no skill**: understanding, ideas, worries, questions. Then each ranks the six skills and **picks one**: frontend, backend, AI/ML, MLOps, DevOps or database (clashes are resolved in order, so all six skills are covered). |
| 3 | Skill lens | Each developer re-thinks the problem through their skill and writes a concrete proposal, still alone. |
| 4 | Conversation | The scrum master checks in (agreements, open threads, who should engage); in between, developers speak freely, one at a time, each hearing everything said so far: they build on, challenge, innovate, concede and rebut each other by name. Material objections become numbered disputes (`DSP-001`) that the targeted developer answers in their own turn. There are no fixed rounds: the scrum master wraps up when no critical objection is open, the folder structure and architecture shape have been discussed, and everyone has spoken. |
| 5 | Questions | Questions raised anywhere in the conversation are merged, filtered and hard-capped at 5 in Python, then asked one at a time (Enter = recommended default). |
| 6 | Rethink | Once your answers are in, every developer rethinks with the whole conversation in front of them: what changed, what they hold, new conflicts, advice for the scrum master. |
| 7 | Decisions | The scrum master records each decision with rejected alternatives. Any dispute they skip becomes a visible `UNRESOLVED` decision. |
| 8 | Specification | One canonical spec is validated, including Mermaid diagrams (system context, architecture, flows, data model) and the directory tree. Invalid diagrams are replaced by ones built from the components. |
| 9 | Design review | Every developer votes on the directory structure and the architecture diagram, asks for concrete changes and replies to colleagues. Requests are applied, then everyone looks again (up to 2 rounds). Documents and `minutes.md` are then rendered. |
| 10 | Verify | Deterministic checks (ids, coverage, cross-document agreement, Mermaid validity, directory tree in every document). One bounded repair pass if they fail. |

`minutes.md` is the transcript: blind thoughts, who took which skill, every proposal, every line of the conversation, objections and answers, your answers, the rethink and the decisions.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env              # then set GEMINI_API_KEY (and optionally GEMINI_MODEL)
```

## The TUI (default in a real terminal)

Running `python -m council` opens a full-screen interface so you can oversee the whole meeting:

| Area | What you see |
|---|---|
| Left: **Stages** | The 10 stages, with the current one highlighted. |
| Left: **Council** | Each member's live state (waiting, thinking, writing, retrying, done, failed), seconds elapsed and characters produced. |
| **Feed** tab (`f`) | The conversation as it happens: each line says who is talking to whom and how (build on, challenge, innovate, rebut, concede), plus proposals, objections and decisions. |
| Member tabs (`1`-`6`, `7` = Scrum Master) | One tab per developer (renamed with their skill once picked) and the scrum master, with the raw model output streaming token by token, including retries. Thought summaries appear in dim italics on Gemini thinking models. |
| **Activity** tab (`l`) | Every request sent, rate-limit wait, retry and failure, with timestamps. |
| **Documents** tab (`p` PRD, `t` Technical, `d` Design, `m` minutes, `v` verification) | The finished documents rendered in place. |

Product questions appear as a pop-up: arrow keys to choose, Enter to confirm, Esc for the recommended default. `q` quits; completed stages are saved and `resume` continues. Use `--plain` for simple scrolling output (also used automatically when output is piped).

Gemma/Gemini models on the free tier return 429/503 under load. The client waits out rate limits (honouring the server's retry hint, shared across parallel calls) and retries transient errors; you can watch this in the Activity tab.

## Use

```text
python -m council run ...                  # prompt -> meeting -> your approval -> sprints (see below)
python -m council                          # the meeting alone: opens the TUI with a start form
python -m council --name "My App" --problem-file examples/problem.md --repo ./my-repo --constraint "Python" -y
python -m council resume output/my-app     # continue an interrupted meeting
python -m council revise output/my-app --feedback "Add CSV export"
```

Output goes to `output/<project-slug>/` (git-ignored): `input.md`, `repo_snapshot.json`, `blind/`, `roster.json`, `proposals/`, `conversation/round-N.json`, `reconsiderations/`, `disputes.json`, `questions.json`, `decisions.json`, `specification.json`, the three documents, `minutes.md`, `verification_report.md`, `meeting.json`, `usage.json`. Revisions keep the previous version in `revisions/<timestamp>/`.

Exit codes: `0` success, `1` error, `2` finished but verification still fails, `130` interrupted.

## Layout: independent modules

Each concern lives in one folder and may only import what the table allows (`tests/test_architecture.py` enforces it).

| Folder | What it is | May import |
|---|---|---|
| `harness/` | The coding agent engine, modelled on opencode: sessions in SQLite, compaction, instruction memory, skills, agents, permissions, tools. | itself |
| `council_a2a/` | Agent2Agent protocol over gRPC, built on the official `a2a-sdk` | itself |
| `memory/` | Project memory (whole-codebase context) and cross-project memory (what the team learned) | itself |
| `meetings/` | Planning mode: blind thinking, skill picking, the pod conversation, questions, decisions, specification, design review, documents, verification, the TUI | `council_a2a` |
| `team/` | Agent mode: developers that build, branch, test and merge a project; `team/agile/` is the sprint playbook (work gate, ceremonies, reports, the human's desk) | `harness`, `council_a2a`, `meetings`, `memory` |
| `council/` | The application entry point (`python -m council`) | everything |

```text
meetings/   cli.py config.py models.py prompts.py gemini_client.py meeting.py conversation.py questions.py
            synthesis.py documents.py verification.py design_review.py repository.py storage.py tui.py system_prompts/
harness/    schema/ ai/ db/ instructions/ session/ tool/ util/
team/       engine.py plan.py scheduler.py repo.py channel.py design.py gitbrain.py tui.py cli.py agile/
council/    cli.py pipeline.py __main__.py
tests/      one folder per module: tests/meetings  tests/harness  tests/team  (run with: pytest; no network)
```

## Tests

```text
pytest                 # offline, uses a fake Gemini client
RUN_LIVE=1 pytest -k live   # opt-in real API smoke test
```

## Safety

Repository content is untrusted data and is delimited as such in prompts. `.env`, keys and credential-like files are never read; secret-looking lines are redacted. The Gemini key is never written to logs or artifacts. The problem statement and repository excerpts are sent to the Gemini API, so only point this at material you are happy to send.

## From a prompt to a built project, in sprints

```text
python -m council run --name "My App" --problem-file examples/problem.md      # the whole thing
python -m council run --from-meeting output/my-app                            # skip the meeting, build from finished documents
python -m council build output/my-app --sprint-capacity 6 --max-days 3        # the build alone
```

One command takes a prompt through everything:

1. **Kickoff.** The pod meeting and its Q&A produce `PRD.md`, `Technical_Approach.md` and `Design.md`.
2. **You accept the documents.** The first set is never accepted automatically. You read them in full, then approve, or decline with what should change (the integrator revises them and asks again). Nothing is coded before you say yes.
3. **Sprints.** Each sprint is planned from the backlog, worked in days, and closed with ceremonies:

| Ceremony | What happens | Document (in `docs/agile/` on the integration branch) |
|---|---|---|
| Sprint planning | The scrum master picks features to fit the team's capacity (later sprints follow the team's measured velocity); each developer commits or raises a concern | `sprint-NN/sprint_backlog.md`, `product_backlog.md` |
| Work day | Every developer works until a task is done or their step budget is spent | |
| Daily standup | After each day every developer reports done / next / blockers from real facts (the task log and git); blockers become impediments and the scrum master resolves what it can | `sprint-NN/standups/standup-NN.md`, `impediments.md` |
| Sprint review | Verification runs on the integration branch; each developer demos; the scrum master judges the goal | `sprint-NN/review.md` |
| Sprint report | Planned vs delivered, burndown, who delivered what, velocity trend, model use | `sprint-NN/sprint_report.md`, `velocity.md` |
| Retrospective | Went well / badly; up to three actions become working agreements every developer sees in their next task, and a lesson goes to long-term memory | `sprint-NN/retrospective.md` |
| Document sync | The PRD, technical approach and design are brought in line with what was built. Routine edits are applied and logged; a major one (scope, architecture, stack, contract, data model) waits for your yes | `CHANGELOG.md` |

**Coding stops during every ceremony.** A work gate freezes the developers between steps (never mid-step); a standup, review or retrospective never overlaps with code being written, and merges wait too. Failed features go back into a later sprint once; unfinished ones are carried over.

**You are in charge while it runs.** In the full-screen view:

| Key | What it does |
|---|---|
| `i` | Interrupt. All coding pauses at the next step boundary and you can speak to the team. Write plainly (the scrum master works out whether it is guidance, a change of scope, or a stop-and-rethink) or prefix `/note`, `/scope` or `/rethink`. A scope change triggers emergency replanning: features are dropped (a running one is cancelled and its half-done work discarded), added or reordered, and the documents are updated. A rethink asks the developers what is wrong and brings you a course correction to approve. Press Resume when you are done. |
| `n` | Leave a note for the next standup; the team keeps working. |
| `p` | Open the decisions waiting for you. Major decisions (the first documents, a design change the team voted for, a PRD amendment, a course correction) always wait for you; the developer who proposed it counts as resting meanwhile, so the others carry on. |
| `r` | The sprint tab. |

Your instructions outrank the team's own decisions, are logged in `docs/agile/human_directives.md`, and are given to every developer in each later task. Every conversation (standups, votes, briefings, your own words to the developers) travels over A2A and is written to `a2a-audit.jsonl`.

Flags: `--sprint-capacity N`, `--max-days N`, `--steps-per-day N`, `--unattended` (approve everything automatically, for CI), `--no-agile` (one flat run, no sprints). With `--plain`, decisions are asked at the prompt but you cannot interrupt mid-run.

When the team is done it leaves `final/<run>` for you to review and merge into main. Nothing is ever merged into main for you.

### The coding harness

`harness/` is a Python port of opencode's logic (sessions, compaction, tools, permissions, agents, subagents, slash commands, a run coordinator and a session inbox for steering and queued input). Each developer runs their own harness in their own clone.

## Docs

- [docs/PRD.md](docs/PRD.md), [docs/Technical_Approach.md](docs/Technical_Approach.md): the product spec
- [docs/STATUS.md](docs/STATUS.md): what is built in the harness and what is left
- [examples/](examples): sample problem statements to try the meeting on
