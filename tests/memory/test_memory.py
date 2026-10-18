"""Project memory (code map, compacted log) and cross-project memory (lessons, recall, profiles, promoted skills)."""

import asyncio
import time
from pathlib import Path

from harness.skill_file import Parsed, parse
from memory import LessonStore, ProjectLog, RunFacts, facts_to_lessons, parse_lessons, relevant, scan, update_codemap
from memory.project import CHECKPOINT_HEADING, render_codemap


def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ code map

def test_codemap_describes_every_file_from_the_code_itself(tmp_path):
    put(tmp_path / "app" / "storage.py", '"""Persist todos in a JSON file."""\n\nclass Store:\n    def add(self): ...\n    def list(self): ...\n    def _private(self): ...\n\ndef load(path): ...\nasync def sync(): ...\ndef _hidden(): ...\n')
    put(tmp_path / "web" / "app.js", "// The browser entry point\nexport function render() {}\nconst go = async (x) => x\nclass View {}\n")
    put(tmp_path / "README.md", "# Todo CLI\n\nA tiny tool.\n")
    put(tmp_path / "node_modules" / "junk" / "x.js", "function ignored() {}")
    put(tmp_path / ".git" / "config", "[core]")
    put(tmp_path / "broken.py", "def (:\n")
    files = {f.path: f for f in scan(tmp_path)}
    assert set(files) == {"app/storage.py", "web/app.js", "README.md", "broken.py"}
    storage = files["app/storage.py"]
    assert storage.purpose == "Persist todos in a JSON file." and storage.symbols == ["class Store (add, list)", "def load", "async def sync"]
    assert files["web/app.js"].purpose == "The browser entry point" and set(files["web/app.js"].symbols) >= {"render", "View"}
    assert files["README.md"].purpose == "Todo CLI" and files["broken.py"].symbols == []
    text = render_codemap(list(files.values()), "Todo")
    assert "# Code map — Todo" in text and "## app/" in text and "`storage.py` (" in text and "class Store (add, list)" in text


def test_update_codemap_writes_into_docs_and_does_not_map_itself(tmp_path):
    put(tmp_path / "a.py", '"""A."""\n')
    target = update_codemap(tmp_path, "P")
    assert target == tmp_path / "docs" / "CODEMAP.md" and "`a.py`" in target.read_text(encoding="utf-8")
    again = update_codemap(tmp_path, "P")
    assert "CODEMAP.md" not in again.read_text(encoding="utf-8").split("Updated after every merge.")[1]


def test_codemap_truncates_cleanly_for_huge_repositories(tmp_path):
    for i in range(60):
        put(tmp_path / f"pkg{i:02d}" / "m.py", '"""Module %d with a fairly long description line to take up room."""\n' % i)
    text = render_codemap(scan(tmp_path), max_chars=1500)
    assert len(text) < 1800 and "map truncated:" in text


# ------------------------------------------------------------------ the log

def test_log_appends_entries_and_round_trips(tmp_path):
    log = ProjectLog(tmp_path, "Todo")
    run(log.add("Merged feature/db", ["owner DEV_6", "files: db.py"]))
    run(log.add("Design change approved", ["EventBus contract"]))
    checkpoint, entries = log.read()
    assert checkpoint == "" and len(entries) == 2 and entries[0].startswith("### ") and "owner DEV_6" in entries[0]
    assert log.text().startswith("# Project memory — Todo") and "## Log" in log.text()


def test_old_entries_are_folded_into_a_checkpoint_when_the_log_outgrows_its_budget(tmp_path):
    seen = []

    async def summarize(previous, folded):
        seen.append((previous, folded))
        return "- Decisions: use SQLite\n- Ownership: DEV_6 owns storage"

    log = ProjectLog(tmp_path, "Todo", budget=900, keep=3)
    for i in range(10):
        run(log.add(f"Merged feature {i}", [f"detail {i} " + "x" * 80], summarize))
    checkpoint, entries = log.read()
    assert 3 <= len(entries) <= 5 and "feature 9" in entries[-1] and "feature 0" not in "\n".join(entries)  # the newest stay verbatim
    assert "use SQLite" in checkpoint and seen and "feature 0" in seen[0][1]
    assert CHECKPOINT_HEADING in log.text() and len(log.text()) < 2500
    assert len(seen) == 1 or any("use SQLite" in prev for prev, _ in seen[1:])  # later folds build on the earlier checkpoint


def test_without_a_summarizer_or_when_it_fails_the_log_is_still_compacted(tmp_path):
    async def broken(previous, folded):
        raise RuntimeError("model down")

    for name, summarizer in (("none", None), ("broken", broken)):
        log = ProjectLog(tmp_path / name, "P", budget=600, keep=2)
        for i in range(8):
            run(log.add(f"Merged {i}", ["x" * 120], summarizer))
        checkpoint, entries = log.read()
        assert len(entries) == 2 and "Merged 0" in checkpoint  # the titles survive mechanically


def test_relevant_picks_the_parts_about_the_query():
    text = "## db\n\n- `db.py`: sqlite connection pool\n\n## ui\n\n- `ui.py`: terminal screens and widgets\n\n## api\n\n- `api.py`: http handlers\n"
    out = relevant(text, "change the sqlite connection settings")
    assert "sqlite" in out and "terminal" not in out and "http" not in out
    assert relevant(text, "zzzz qqqq", 40) == text[:40] and relevant("", "x") == ""


# ------------------------------------------------------------------ lessons

def test_similar_lessons_strengthen_instead_of_piling_up(tmp_path):
    store = LessonStore(tmp_path)
    a = store.add("Two features that edit the same file collide at merge; give them one owner.", project="p1", tags=["merge"])
    b = store.add("Two features that edit the same file collide at merge, give them one owner", project="p2", tags=["plan"])
    assert a is b and len(store.lessons) == 1 and a.seen == 2 and a.projects == ["p1", "p2"] and set(a.tags) == {"merge", "plan"}
    c = store.add("Pin dependency versions in the lockfile.", skill="DEVOPS", project="p1")
    assert len(store.lessons) == 2 and c.skill == "DEVOPS"


def test_lessons_survive_a_restart_and_a_damaged_line(tmp_path):
    store = LessonStore(tmp_path)
    store.add("Keep migrations reversible.", skill="DATABASE", project="p1")
    store.record_run("DATABASE", features=3, conversations=1)
    store.save()
    with open(tmp_path / "lessons.jsonl", "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    again = LessonStore(tmp_path)
    assert [l.text for l in again.lessons] == ["Keep migrations reversible."] and again.profiles["DATABASE"].features == 3


def test_recall_prefers_matching_confirmed_lessons_of_the_right_skill(tmp_path):
    store = LessonStore(tmp_path)
    store.add("Index foreign keys in the database schema before loading data.", skill="DATABASE", project="p1")
    store.add("Index foreign keys in the database schema before loading data.", skill="DATABASE", project="p2")
    store.add("Keep terminal screens responsive by rendering off the main loop.", skill="FRONTEND", project="p1")
    store.add("Write the integration test before wiring features together.", project="p1")
    hits = store.recall("design the database schema with foreign keys", skill="DATABASE")
    assert hits and hits[0].skill == "DATABASE" and all(h.skill in ("", "DATABASE") for h in hits)
    assert not any("terminal" in h.text for h in hits)
    assert store.recall("zzz qqq") == [] and store.recall("") == []
    text = store.render(hits)
    assert text.startswith("Lessons from earlier projects") and "- Index foreign keys" in text and store.render([]) == ""


def test_old_unconfirmed_lessons_are_pruned_first(tmp_path):
    store = LessonStore(tmp_path)
    old = store.add("An old lesson nobody confirmed again.", project="p1")
    old.updated = time.time() - 900 * 86400
    texts = [
        "Cache invalidation rules belong in the design document.",
        "Retry budgets prevent a failing dependency from taking everything down.",
        "Schema migrations must be reversible before they ship.",
        "Rotate logs by size so disks never fill during long runs.",
        "Feature flags let unfinished work merge without being released.",
    ]
    for i, text in enumerate(texts):
        store.add(text, project=f"q{i}")
    assert store.prune(max_lessons=5) == 1 and old not in store.lessons


def test_lessons_seen_on_two_projects_become_skill_files_the_harness_can_load(tmp_path):
    store = LessonStore(tmp_path)
    store.add("Index foreign keys before loading data.", skill="DATABASE", project="p1")
    store.add("Index foreign keys before loading data.", skill="DATABASE", project="p2")
    store.add("Agree the interface before building in parallel.", project="p1")
    store.add("Agree the interface before building in parallel.", project="p1")  # the same project twice is not two projects
    written = store.write_skills()
    assert [p.parent.name for p in written] == ["council-database-lessons"]
    content = written[0].read_text(encoding="utf-8")
    parsed = parse(written[0].parent.parent, written[0], content)
    assert isinstance(parsed, Parsed) and parsed.skill.id == "council-database-lessons" and "Index foreign keys" in parsed.skill.content
    assert "seen on 2 projects" in content and "parallel" not in content


def test_profiles_describe_experience(tmp_path):
    store = LessonStore(tmp_path)
    assert store.describe("BACKEND") == ""
    store.record_run("BACKEND", features=4, conversations=2, failures=1, note="owned the storage layer")
    store.record_run("BACKEND", features=1)
    assert store.describe("BACKEND") == "Experience: 2 earlier project(s), 5 feature(s) built, 2 merge conversation(s), 1 failure(s)."
    assert store.profile("BACKEND").notes == ["owned the storage layer"]


# ------------------------------------------------------------------ learning from a run

def test_run_facts_become_actionable_lessons():
    facts = RunFacts(
        "Todo", features=4,
        conflicts=[{"feature": "left", "files": ["shared.py"], "resolved": True}, {"feature": "right", "files": ["x.py"], "resolved": False}],
        failed_features=[{"feature": "api", "owner": "DEV_2", "skill": "BACKEND", "reason": "task timed out\nafter 30 minutes"}],
        verification_failures=[{"command": "pytest -q", "tail": "2 failed\n in test_api"}],
        decisions=[{"title": "Use event bus", "approved": True, "proposer_skill": "BACKEND"}, {"title": "Rewrite all", "approved": False, "proposer_skill": "FRONTEND"}],
        unresolved_merges=1,
    )
    lessons = facts_to_lessons(facts)
    sources = [l["source"] for l in lessons]
    assert sources.count("conflict") == 3 and "failure" in sources and "verification" in sources and sources.count("design") == 2
    text = "\n".join(l["text"] for l in lessons)
    assert "shared.py" in text and "one owner" in text and "could not be resolved" in text and "task timed out after 30 minutes" in text and "pytest -q" in text
    assert all("\n" not in l["text"] for l in lessons)
    assert facts_to_lessons(RunFacts("Clean run")) == []


def test_distilled_lessons_are_parsed_defensively():
    reply = 'Here you go: {"lessons":[{"text":"Split work along file boundaries so parallel features never collide.","skill":"backend","tags":["plan"]},{"text":"short"},{"nope":1},"x"]} thanks'
    out = parse_lessons(reply)
    assert out == [{"text": "Split work along file boundaries so parallel features never collide.", "skill": "BACKEND", "tags": ["plan"], "source": "distilled"}]
    assert parse_lessons("no json here") == [] and parse_lessons("{broken") == []
