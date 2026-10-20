import asyncio
import re
from pathlib import Path

from meetings import exploration
from meetings.config import Settings
from meetings.exploration import Capability, DevNotes, Exploration, FileNote, Layer, Overview
from meetings.meeting import Reporter, run_meeting
from meetings.models import MeetingInput
from meetings.storage import MeetingStore
from tests.meetings.fakes import FakeLLM

SETTINGS = Settings(api_key="k", model="fake")


def make_repo(root: Path) -> Path:
    files = {
        "README.md": "# Jarvis\nA voice assistant.\n",
        "pyproject.toml": "[project]\nname='jarvis'\n",
        "jarvis/__init__.py": "",
        "jarvis/core/bus.py": '"""The event bus."""\nclass EventBus:\n    def publish(self, e): ...\n',
        "jarvis/core/app.py": "from jarvis.core.bus import EventBus\nbus = EventBus()\n",
        "jarvis/plugins/router/rule_router.py": "class RuleRouter:\n    def route(self, text): ...\n",
        "tests/test_router.py": "def test_route():\n    assert True\n",
        ".env": "GEMINI_API_KEY=AIzaSyA1234567890123456789012345678901234\n",
        "package-lock.json": "{}" * 50,
        "logo.png": "binary",
        "node_modules/x/index.js": "x",
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (root / "blob.py").write_bytes(b"\0\1\2" * 100)
    return root


def read_notes(prompt: str, stage: str) -> DevNotes:
    paths = re.findall(r"=== FILE: (\S+)", prompt)
    return DevNotes(notes=[FileNote(path=p, purpose=f"purpose of {p}", offers=[f"{Path(p).stem} things"], depends_on=["jarvis/core/bus.py"] if p.endswith("app.py") else [],
                                    conventions=["injected collaborators"] if p.endswith("bus.py") else [])
                           for p in paths if not p.endswith("README.md")])  # the model forgets README.md on purpose


def overview(prompt: str, stage: str) -> Overview:
    return Overview(architecture="Core with plugin families.", layers=[Layer(name="core", paths=["jarvis/core"], role="contracts and loop")], rules=["core never imports plugins"],
                    capabilities=[Capability(name="EventBus", where="jarvis/core/bus.py", what="publish/subscribe")], do_not_recreate=["An EventBus already exists in jarvis/core/bus.py; extend it."])


def fake() -> FakeLLM:
    llm = FakeLLM()
    llm.overrides[DevNotes] = read_notes
    llm.overrides[Overview] = overview
    return llm


def test_only_text_worth_reading_is_read_and_the_central_files_come_first(tmp_path):
    files, skipped = exploration.readable_files(make_repo(tmp_path))
    names = [f for f, _ in files]
    assert "jarvis/core/bus.py" in names and "tests/test_router.py" in names
    assert not any(n in names for n in (".env", "package-lock.json", "logo.png", "node_modules/x/index.js"))
    assert any(".env" in s and "secret" in s for s in skipped)
    assert names.index("README.md") < names.index("jarvis/core/bus.py") < names.index("tests/test_router.py")


def test_related_files_go_to_the_same_reader_and_a_small_repo_does_not_need_six(tmp_path):
    files = [("a/x/1.py", 10), ("a/x/2.py", 10), ("b/y/1.py", 10), ("b/y/2.py", 10), ("c/z/1.py", 10), ("c/z/2.py", 10)]
    devs = exploration.developers_for(len(files))
    assert len(devs) == 1
    many = [(f"pkg{i}/mod/f{j}.py", 100) for i in range(12) for j in range(3)]
    spread = exploration.assign(many, exploration.developers_for(len(many)))
    assert len(spread) == 6
    owner = {p: d for d, ps in spread.items() for p in ps}
    assert len({owner[f"pkg0/mod/f{j}.py"] for j in range(3)}) == 1  # a folder is not split between readers
    assert sum(len(v) for v in spread.values()) == len(many)


def test_every_file_is_read_whole_and_a_forgotten_one_still_gets_a_note(tmp_path):
    repo = make_repo(tmp_path / "repo")
    llm = fake()
    prompts: list[str] = []
    original = llm.overrides[DevNotes]
    llm.overrides[DevNotes] = lambda prompt, stage: (prompts.append(prompt), original(prompt, stage))[1]
    store = MeetingStore(tmp_path / "meeting", "fake")
    said: list[str] = []
    rep = Reporter(out=said.append)
    result = asyncio.run(exploration.explore(repo, [], SETTINGS, llm, store, rep))
    paths = {n.path for n in result.notes}
    assert {"README.md", "jarvis/core/bus.py", "jarvis/core/app.py", "tests/test_router.py"} <= paths
    readme = next(n for n in result.notes if n.path == "README.md")
    assert readme.purpose and readme.reader.startswith("DEV_")  # the model skipped it; it is still there
    assert result.overview and result.overview.capabilities[0].name == "EventBus"
    joined = "\n".join(prompts)
    assert "class EventBus" in joined  # the file was read whole, not summarised
    assert "AIzaSy" not in joined  # secrets never reach a prompt
    assert (tmp_path / "meeting" / "exploration.json").exists()


def test_a_resumed_meeting_does_not_read_again(tmp_path):
    repo = make_repo(tmp_path / "repo")
    store = MeetingStore(tmp_path / "meeting", "fake")
    first = asyncio.run(exploration.explore(repo, [], SETTINGS, fake(), store, Reporter(out=lambda _: None)))
    second = fake()
    again = asyncio.run(exploration.explore(repo, [], SETTINGS, second, store, Reporter(out=lambda _: None)))
    assert sum(second.calls.values()) == 0 and again.files_read == first.files_read > 0


def test_a_batch_that_fails_is_reported_not_hidden(tmp_path):
    repo = make_repo(tmp_path / "repo")
    llm = FakeLLM(fail_stages=("explore",))
    llm.overrides[Overview] = overview
    store = MeetingStore(tmp_path / "meeting", "fake")
    warnings: list[str] = []

    class Loud(Reporter):
        def warn(self, text):
            warnings.append(text)

    result = asyncio.run(exploration.explore(repo, [], SETTINGS, llm, store, Loud(out=lambda _: None)))
    assert any("could not read" in w for w in warnings)
    assert result.notes == []


def test_the_digest_tells_the_pod_what_not_to_rebuild(tmp_path):
    result = Exploration(files_read=3, notes=[FileNote(path="a.py", purpose="x")], overview=overview("", ""))
    text = exploration.digest(result)
    assert "Do NOT re-create" in text and "jarvis/core/bus.py" in text and text.startswith("<untrusted_repository_data>")
    assert exploration.digest(Exploration()) == ""


def test_the_meeting_explores_first_shares_it_and_hands_it_to_memory(tmp_path):
    repo = make_repo(tmp_path / "repo")
    llm = fake()
    seen: list[str] = []
    heard = {}

    async def hook(found, meeting_dir):
        heard["files"] = found.files_read
        heard["dir"] = meeting_dir

    inp = MeetingInput(project_name="Jarvis timers", problem="Add timers.", constraints=["stdlib only"], repo_path=str(repo), output_dir=str(tmp_path / "out"))
    original_generate = llm.generate

    async def spy(prompt, schema, *, stage, system=""):
        if stage.startswith("blind:"):
            seen.append(prompt)
        return await original_generate(prompt, schema, stage=stage, system=system)

    llm.generate = spy
    result = asyncio.run(run_meeting(inp, SETTINGS, llm, Reporter(out=lambda _: None), interactive=False, on_explored=hook))
    assert result.report.passed
    assert heard["files"] >= 5 and Path(heard["dir"]) == result.out_dir
    assert seen and all("Do NOT re-create" in p and "EventBus already exists" in p for p in seen)  # every developer thought with the repo's own contents in front of them
    assert (result.out_dir / "exploration.json").exists()


def test_a_failing_memory_hook_does_not_stop_the_meeting(tmp_path):
    repo = make_repo(tmp_path / "repo")
    warned: list[str] = []

    class Rep(Reporter):
        def warn(self, text):
            warned.append(text)

    def hook(found, meeting_dir):
        raise RuntimeError("disk full")

    inp = MeetingInput(project_name="Jarvis timers", problem="Add timers.", constraints=[], repo_path=str(repo), output_dir=str(tmp_path / "out"))
    result = asyncio.run(run_meeting(inp, SETTINGS, fake(), Rep(out=lambda _: None), interactive=False, on_explored=hook))
    assert result.report.passed and any("disk full" in w for w in warned)
