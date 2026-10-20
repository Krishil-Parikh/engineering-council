import asyncio
from pathlib import Path

from meetings.exploration import Capability, Exploration, FileNote, Layer, Overview
from memory.team import TeamMemory
from team.explore_memory import make_hook, memory_root


def found(root: Path) -> Exploration:
    (root / "jarvis" / "core").mkdir(parents=True)
    (root / "jarvis" / "core" / "bus.py").write_text("class EventBus:\n    pass\n", encoding="utf-8")
    (root / "jarvis" / "core" / "app.py").write_text("from jarvis.core.bus import EventBus\n", encoding="utf-8")
    notes = [
        FileNote(path="jarvis/core/bus.py", purpose="The event bus every part publishes to.", offers=["EventBus"], conventions=["subscribers never raise"], reader="DEV_1"),
        FileNote(path="jarvis/core/app.py", purpose="Builds the application.", depends_on=["jarvis/core/bus.py"], watch_out=["startup order matters"], reader="DEV_2"),
    ]
    overview = Overview(architecture="Core with plugin families.", layers=[Layer(name="core", paths=["jarvis/core"], role="contracts")], rules=["core never imports plugins"],
                        capabilities=[Capability(name="EventBus", where="jarvis/core/bus.py", what="publish/subscribe")], do_not_recreate=["An EventBus already exists in jarvis/core/bus.py"])
    return Exploration(root=str(root), files_read=2, assignments={"DEV_1": ["jarvis/core/bus.py"], "DEV_2": ["jarvis/core/app.py"]}, notes=notes, overview=overview)


def test_reading_the_repository_starts_both_memories(tmp_path):
    mem = TeamMemory(tmp_path / "memory")
    made = mem.ingest_exploration(found(tmp_path / "repo").model_dump())
    assert made["files"] == 2 and made["capabilities"] == 1 and made["layers"] == 1
    project = {(n.kind, n.name) for n in mem.project.nodes()}
    assert ("file", "jarvis/core/bus.py") in project and ("api", "EventBus") in project and ("module", "core") in project
    assert ("note", "Architecture of the repository") in project
    assert any(k == "pitfall" and "EventBus already exists" in n for k, n in project)  # what not to rebuild is a memory of its own
    bus = next(n for n in mem.project.nodes() if n.name == "jarvis/core/bus.py")
    app = next(n for n in mem.project.nodes() if n.name == "jarvis/core/app.py")
    assert bus.importance > app.importance  # a file others depend on matters more
    assert any(rel == "depends_on" and other.name == "jarvis/core/bus.py" for rel, other, outgoing, _ in mem.project.neighbors(app.id))
    assert sorted(mem.agents()) == ["DEV_1", "DEV_2"]  # each developer has a private memory from the first minute
    own = {(n.kind, n.name) for n in mem.agent("DEV_1").nodes()}
    assert ("file", "jarvis/core/bus.py") in own and ("note", "What I read at kickoff") in own
    assert ("file", "jarvis/core/app.py") not in own  # DEV_1 did not read it


def test_a_developer_can_recall_what_the_pod_learned(tmp_path):
    mem = TeamMemory(tmp_path / "memory")
    mem.ingest_exploration(found(tmp_path / "repo").model_dump())
    text = mem.recall_sync("DEV_3", "I need an event bus for timer ticks")
    assert "EventBus" in text and "jarvis/core/bus.py" in text


def test_the_hook_writes_where_the_build_will_look_and_the_build_sees_it(tmp_path):
    meeting = tmp_path / "meeting"
    opened = []
    hook = make_hook(api_key=None, on_memory=opened.append, memory_model=None)
    asyncio.run(hook(found(tmp_path / "repo"), meeting))
    assert opened and opened[0].root == memory_root(meeting) == meeting / "team" / "memory"
    later = TeamMemory(meeting / "team" / "memory")  # what TeamEngine opens for the build
    assert ("api", "EventBus") in {(n.kind, n.name) for n in later.project.nodes()}
    assert sorted(later.agents()) == ["DEV_1", "DEV_2"]
    assert any(n.kind == "file" and n.name == "jarvis/core/app.py" for n in later.project.nodes())  # and the exact import map came from the code itself
