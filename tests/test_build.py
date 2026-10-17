import asyncio
import json
import subprocess

from engineering_council import synthesis
from engineering_council.build import agents_md, build_project, pick_developer, step_prompt
from engineering_council.models import Roster, Step
from tests.fakes import draft_spec
from tests.harness.conftest import ScriptedModel, call, calls

SKILLS = {"DEV_1": "FRONTEND", "DEV_2": "BACKEND", "DEV_3": "AIML", "DEV_4": "MLOPS", "DEV_5": "DEVOPS", "DEV_6": "DATABASE"}


def finished_meeting(tmp_path, commands=("echo verified",)):
    spec = synthesis.finalize_spec(draft_spec().model_copy(update={"verification_commands": list(commands)}), [])
    spec = spec.model_copy(update={"project_name": "Todo CLI"})
    d = tmp_path / "meeting"
    d.mkdir()
    (d / "specification.json").write_text(spec.model_dump_json(), encoding="utf-8")
    (d / "roster.json").write_text(Roster(skills=SKILLS).model_dump_json(), encoding="utf-8")
    for doc in ("PRD.md", "Technical_Approach.md", "Design.md"):
        (d / doc).write_text(f"# {doc}\n", encoding="utf-8")
    return d, spec


def test_steps_go_to_the_developer_whose_skill_fits(tmp_path):
    _, spec = finished_meeting(tmp_path)
    load: dict[str, int] = {}
    assert pick_developer(Step(order=1, title="Create the SQL schema and migrations", details="tables and indexes"), spec, SKILLS, load) == "DEV_6"
    assert pick_developer(Step(order=2, title="Dockerfile and CI workflow", details="deploy pipeline"), spec, SKILLS, load) == "DEV_5"
    assert pick_developer(Step(order=4, title="Storage", details="Implement storage"), spec, SKILLS, load) == "DEV_6"  # "rag" inside "storage" must not match
    assert pick_developer(Step(order=3, title="Terminal screens", details="render the UI view"), spec, SKILLS, load) == "DEV_1"


def test_project_memory_and_step_prompt_carry_the_spec(tmp_path):
    _, spec = finished_meeting(tmp_path)
    md = agents_md(spec)
    assert "todo-cli/" in md and "Python 3.11" in md and "echo verified" in md
    prompt = step_prompt(spec, spec.implementation_sequence[0], [], "DEV_2")
    assert "step 1" in prompt and "docs/Design.md" in prompt and "add_task" in prompt


def test_build_runs_every_step_commits_and_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    meeting, spec = finished_meeting(tmp_path)
    n = len(spec.implementation_sequence)
    replies = []
    for step in sorted(spec.implementation_sequence, key=lambda s: s.order):
        replies += [
            calls(call("write", path=f"src_{step.order}.py", content=f"# step {step.order}\n")),
            calls(call("shell", command=f'git add -A && git commit -q -m "step {step.order}: {step.title}"')),
            f"Built step {step.order}.",
        ]
    model = ScriptedModel(*replies)
    steps_seen: list[str] = []
    result = asyncio.run(build_project(meeting, model, on_step=steps_seen.append))
    project = meeting / "project"
    assert result.passed and [s.ok for s in result.steps] == [True] * n and len(steps_seen) == n
    assert (project / "AGENTS.md").exists() and (project / "docs" / "Design.md").exists()
    log = subprocess.run(["git", "log", "--oneline"], cwd=project, capture_output=True, text=True).stdout
    assert "step 1:" in log and f"step {n}:" in log and "Add specification" in log
    assert "AGENTS.md" not in log  # file names are not commit text; sanity check only
    report = (meeting / "build_report.md").read_text(encoding="utf-8")
    assert "verification passed" in report and "echo verified" in report
    # each step ran as the chosen developer, wearing their skill, and saw the project's AGENTS.md
    assert "DEV_" in model.calls[0]["system"] and "Layout" in model.calls[0]["system"]


def test_failing_verification_is_sent_back_to_a_developer(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    meeting, spec = finished_meeting(tmp_path, commands=("python -c \"import sys; sys.exit(1)\"",))
    model = ScriptedModel(*(["ok"] * len(spec.implementation_sequence)), "tried to fix", "tried again")
    result = asyncio.run(build_project(meeting, model, fix_rounds=2))
    assert not result.passed and any("still failing" in w for w in result.warnings)
    assert any("verification commands fail" in m.text for c in model.calls[len(spec.implementation_sequence):] for m in c["messages"] if m.role == "user")
