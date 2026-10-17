# Engineering Council CLI

A terminal tool that turns a problem statement into three reviewed, consistent specification documents — `PRD.md`, `Technical_Approach.md` and `Design.md` — by running a conversational pod meeting: six developers who each pick a skill, led by a scrum master. Python + Gemini API only. See [PRD.md](PRD.md) and [Technical_Approach.md](Technical_Approach.md) for the product spec this implements.

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

Running `python -m engineering_council` opens a full-screen interface so you can oversee the whole meeting:

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
python -m engineering_council                          # opens the TUI with a start form
python -m engineering_council --name "My App" --problem-file problem.md --repo ./my-repo --constraint "Python" -y
python -m engineering_council resume output/my-app     # continue an interrupted meeting
python -m engineering_council revise output/my-app --feedback "Add CSV export"
```

Output goes to `output/<project-slug>/` (git-ignored): `input.md`, `repo_snapshot.json`, `blind/`, `roster.json`, `proposals/`, `conversation/round-N.json`, `reconsiderations/`, `disputes.json`, `questions.json`, `decisions.json`, `specification.json`, the three documents, `minutes.md`, `verification_report.md`, `meeting.json`, `usage.json`. Revisions keep the previous version in `revisions/<timestamp>/`.

Exit codes: `0` success, `1` error, `2` finished but verification still fails, `130` interrupted.

## Layout

```text
engineering_council/
  cli.py  config.py  models.py  prompts.py  gemini_client.py  repository.py
  meeting.py  questions.py  synthesis.py  documents.py  verification.py  storage.py
  conversation.py      blind thinking, skill picking, the multi-round pod conversation
  system_prompts/      shared rules, developer, scrum master, arbiter, curator, documents...
tests/                 run with: pytest   (fake client, no network)
```

## Tests

```text
pytest                 # offline, uses a fake Gemini client
RUN_LIVE=1 pytest -k live   # opt-in real API smoke test
```

## Safety

Repository content is untrusted data and is delimited as such in prompts. `.env`, keys and credential-like files are never read; secret-looking lines are redacted. The Gemini key is never written to logs or artifacts. The problem statement and repository excerpts are sent to the Gemini API, so only point this at material you are happy to send.
