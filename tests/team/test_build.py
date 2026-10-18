from meetings import synthesis
from team.build import agents_md, pick_developer
from meetings.models import Roster, Step
from tests.meetings.fakes import draft_spec

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


def test_project_memory_carries_the_spec(tmp_path):
    _, spec = finished_meeting(tmp_path)
    md = agents_md(spec)
    assert "todo-cli/" in md and "Python 3.11" in md and "echo verified" in md
    assert "docs/Design.md" in md and "docs/CODEMAP.md" in md and "docs/MEMORY.md" in md
