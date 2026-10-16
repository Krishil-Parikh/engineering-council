# Engineering Council CLI

A terminal tool that turns a problem statement into three reviewed, consistent specification documents — `PRD.md`, `Technical_Approach.md` and `Design.md` — by running a structured meeting between four AI perspectives. Python + Gemini API only. See [PRD.md](PRD.md) and [Technical_Approach.md](Technical_Approach.md) for the product spec this implements.

## How the meeting works

| # | Stage | What happens |
|---|---|---|
| 1 | Inspect | Optional read-only repository snapshot (secrets excluded and redacted, nothing executed). |
| 2 | Proposals | `SYSTEMS_ARCHITECT`, `PRODUCT_UX`, `PRAGMATIC_MVP`, `RED_TEAM_QA` prepare **alone**, in parallel. |
| 3 | Review | Each member reads the others' proposals, endorses good ideas, and raises typed objections (`CRITICAL`/`MAJOR`/`NITPICK`) or `NO_MATERIAL_OBJECTION`. |
| 4 | Rebuttal | Each member answers every objection against them: accept, partially accept, or reject with a reason. |
| 5 | Questions | Questions are merged, filtered and hard-capped at 5 in Python, then asked one at a time (Enter = recommended default). |
| 6 | Decisions | The arbiter records each decision with rejected alternatives. Any dispute it skips becomes a visible `UNRESOLVED` decision. |
| 7 | Specification | One canonical spec is validated, then the three documents and `minutes.md` are rendered from it. |
| 8 | Verify | Deterministic checks (ids, coverage, cross-document agreement). One bounded repair pass if they fail. |

`minutes.md` reads like real meeting minutes: who said what, every objection and rebuttal, your answers, and the decisions.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env              # then set GEMINI_API_KEY (and optionally GEMINI_MODEL)
```

## Use

```text
python -m engineering_council                          # interactive
python -m engineering_council --name "My App" --problem-file problem.md --repo ./my-repo --constraint "Python" -y
python -m engineering_council resume output/my-app     # continue an interrupted meeting
python -m engineering_council revise output/my-app --feedback "Add CSV export"
```

Output goes to `output/<project-slug>/` (git-ignored): `input.md`, `repo_snapshot.json`, `proposals/`, `reviews/`, `rebuttals/`, `disputes.json`, `questions.json`, `decisions.json`, `specification.json`, the three documents, `minutes.md`, `verification_report.md`, `meeting.json`, `usage.json`. Revisions keep the previous version in `revisions/<timestamp>/`.

Exit codes: `0` success, `1` error, `2` finished but verification still fails, `130` interrupted.

## Layout

```text
engineering_council/
  cli.py  config.py  models.py  prompts.py  gemini_client.py  repository.py
  meeting.py  questions.py  synthesis.py  documents.py  verification.py  storage.py
  system_prompts/      role prompts (00 shared rules ... 10 targeted patch)
tests/                 run with: pytest   (fake client, no network)
```

## Tests

```text
pytest                 # offline, uses a fake Gemini client
RUN_LIVE=1 pytest -k live   # opt-in real API smoke test
```

## Safety

Repository content is untrusted data and is delimited as such in prompts. `.env`, keys and credential-like files are never read; secret-looking lines are redacted. The Gemini key is never written to logs or artifacts. The problem statement and repository excerpts are sent to the Gemini API, so only point this at material you are happy to send.
