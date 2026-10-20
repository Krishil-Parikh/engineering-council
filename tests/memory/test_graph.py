"""Memory as a graph, and how it is searched: a shared project memory every agent writes to, a private memory per agent, and a retrieval pipeline that finds what
words alone would miss."""

import time

from memory import extract as X
from memory.graph import MemoryGraph
from memory.retrieval import BM25, Retriever, cosine, personalized_pagerank, rrf, tokens
from memory.team import TeamMemory

CONCEPTS = {
    "time": {"clock", "time", "timer", "timers", "expire", "expiry", "deadline", "monotonic", "sleep", "sleeping", "countdown", "testable"},
    "speech": {"speech", "speak", "speaking", "spoken", "voice", "tts", "alert", "alerts", "announce"},
    "test": {"test", "tests", "pytest", "fixture", "mock", "fake", "verify", "testable"},
    "git": {"git", "commit", "branch", "merge", "conflict", "push"},
}


class FakeModel:
    """Understands 'same meaning' by word families, so a question can use other words than the memory. Also answers the JSON prompts from a script."""

    embed_model = "fake-embed"

    def __init__(self, replies=None):
        self.replies, self.prompts, self.embedded = list(replies or []), [], 0

    def embed(self, texts, query=False):
        self.embedded += len(texts)
        return [[float(any(w in family for w in tokens(t))) for family in CONCEPTS.values()] for t in texts]

    def generate_json(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else {}


# ---------------------------------------------------------------------------------------------- the store

def test_a_memory_is_a_node_and_writing_it_again_adds_to_it_instead_of_repeating_it():
    g = MemoryGraph()
    g.node("note", "clock", "Use the injected Clock, never time.monotonic().", "DEV_1", ["time"], 6)
    g.node("note", "clock", "Use the injected Clock, never time.monotonic().", "DEV_2", [], 8)
    g.node("note", "clock", "FakeClock lives in contracts.py")
    n = g.get("note:clock")
    assert n.mentions == 3 and n.text.count("injected Clock") == 1 and "FakeClock" in n.text and n.importance == 8 and n.tags == ["time"]


def test_a_replaced_fact_keeps_its_history_and_is_left_out_of_what_is_found():
    g = MemoryGraph()
    old = g.node("convention", "timer limit", "At most 5 timers.")
    new = g.node("convention", "timer limit v2", "At most 10 timers, configurable with MAX_TIMERS.")
    g.supersede(old.id, new.id, "the brief changed")
    assert [n.name for n in g.nodes()] == ["timer limit v2"] and g.get(old.id).valid_to is not None and g.get(old.id).superseded_by == new.id
    assert [n.name for n in g.history("timer limit")] == ["timer limit", "timer limit v2"]
    assert g.stats()["replaced"] == 1
    hits = Retriever(g).search("how many timers", k=5)
    assert [h.node.name for h in hits] == ["timer limit v2"]


def test_a_graph_survives_a_restart(tmp_path):
    path = tmp_path / "g.sqlite"
    g = MemoryGraph(path)
    g.node("note", "a", "first")
    g.link(("note", "a"), "relates_to", ("note", "b"))
    g.close()
    again = MemoryGraph(path)
    assert {n.id for n in again.nodes()} == {"note:a", "note:b"} and [(e.src, e.rel, e.dst) for e in again.edges()] == [("note:a", "relates_to", "note:b")]
    again.close()


# ---------------------------------------------------------------------------------------------- the pieces of retrieval

def test_identifiers_and_paths_are_found_by_their_parts_and_whole():
    assert {"timer", "registry", "py", "timerregistrypy"} <= set(tokens("jarvis/plugins/timer_registry.py"))
    g = MemoryGraph()
    g.node("file", "jarvis/plugins/timer/timer_registry.py", "defines TimerRegistry")
    g.node("file", "jarvis/core/bus.py", "the event bus")
    assert BM25(g.nodes()).search("timer_registry")[0][0] == "file:jarvis/plugins/timer/timer_registry.py"


def test_rank_fusion_puts_what_several_lists_agree_on_first_without_comparing_their_scores():
    fused = rrf([["a", "b", "c"], ["b", "d", "a"], ["b", "a"]])
    assert max(fused, key=fused.get) == "b" and set(fused) == {"a", "b", "c", "d"}


def test_a_walk_from_the_hits_reaches_a_node_that_shares_no_word_with_the_question():
    g = MemoryGraph()
    g.link(("file", "registry.py"), "imports", ("file", "clock.py"))
    g.link(("file", "clock.py"), "imports", ("file", "contracts.py"))
    g.node("pitfall", "tests never sleep", "Real sleeps made CI flaky; inject the clock.")
    g.link(("pitfall", "tests never sleep"), "about", ("file", "clock.py"))
    rank = personalized_pagerank(g, {"file:registry.py": 1.0})
    assert rank["file:clock.py"] > rank["file:contracts.py"] > 0 and rank["pitfall:tests never sleep"] > 0
    assert cosine([1, 0], [1, 0]) == 1 and cosine([1, 0], [0, 1]) == 0


def build_project():
    g = MemoryGraph()
    g.node("convention", "inject time", "Never call time.monotonic() in production code; take a Clock so tests can move time.", "DEV_1", ["testing"], 8)
    g.node("api", "TimerRegistry", "TimerRegistry.next() returns the timer closest to expiry; add() raises when MAX_TIMERS is reached.", "DEV_2", [], 7)
    g.node("pitfall", "speech queue order", "Alerts must wait while Jarvis is speaking or listening, or they cut in over an answer.", "DEV_3", [], 7)
    g.node("note", "git habits", "Commit small and push after each group of commits.", "DEV_4", [], 4)
    g.link(("api", "TimerRegistry"), "depends_on", ("convention", "inject time"))
    return g


def test_hybrid_search_finds_a_memory_that_uses_other_words_than_the_question_and_says_why():
    g = build_project()
    question = "how do I make countdown deadlines testable without sleeping"
    hybrid = Retriever(g, FakeModel()).search(question, k=3)
    assert hybrid[0].node.name in ("inject time", "TimerRegistry")
    assert hybrid[0].signals["dense"] is not None and hybrid[0].signals["cosine"] > 0.9  # found by meaning, and the hit says so
    assert "speech queue order" not in [h.node.name for h in hybrid[:2]] and "git habits" not in [h.node.name for h in hybrid[:2]]


def test_the_graph_brings_in_what_a_hit_depends_on_even_when_the_words_do_not_match():
    g = build_project()
    hits = Retriever(g).search("TimerRegistry next", k=4)
    names = [h.node.name for h in hits]
    assert names[0] == "TimerRegistry" and "inject time" in names  # reached through the depends_on link
    assert {h.node.name: h.signals["via"] for h in hits}["inject time"] == "link"


def test_recent_and_important_memories_win_between_equally_relevant_ones():
    g = MemoryGraph()
    g.node("note", "alpha clock note", "clock detail", "DEV_1", [], 3)
    g.node("note", "beta clock note", "clock detail", "DEV_1", [], 9)
    assert Retriever(g).search("clock detail", k=2)[0].node.name == "beta clock note"
    g2 = MemoryGraph()
    g2.node("note", "old clock note", "clock detail")
    g2.node("note", "new clock note", "clock detail")
    g2._db.execute("UPDATE nodes SET updated=? WHERE name='old clock note'", (time.time() - 30 * 24 * 3600,))
    g2._db.commit()
    g2.version += 1
    assert Retriever(g2).search("clock detail", k=2)[0].node.name == "new clock note"


def test_the_model_can_rewrite_the_question_and_rerank_the_candidates():
    g = build_project()
    model = FakeModel([{"searches": ["scheduling expiry"], "hypothetical": "a convention about injecting a clock"}, {"order": [1, 0]}])
    r = Retriever(g, model)
    query = r.understand("countdown help")
    assert query.variants == ["scheduling expiry"] and "clock" in query.hypothetical
    hits = r.search(query, k=3, rerank=True)
    assert any(h.signals.get("rerank") for h in hits)


# ---------------------------------------------------------------------------------------------- the two tiers

def test_what_an_agent_writes_to_the_project_is_seen_by_the_others_and_what_it_keeps_to_itself_is_not():
    team = TeamMemory()
    team.remember("DEV_1", "project", "api", "TimerRegistry", "Timers are stored sorted by expiry; use TimerRegistry.next().", [("about", "file", "registry.py")], 8)
    team.remember("DEV_1", "me", "preference", "my habit", "I forget to run the safety tests before pushing.")
    mine, theirs = team.recall_sync("DEV_1", "timer registry safety tests pushing"), team.recall_sync("DEV_2", "timer registry safety tests pushing")
    assert "sorted by expiry" in mine and "forget to run the safety tests" in mine
    assert "sorted by expiry" in theirs and "forget to run" not in theirs and "Your own memory" not in theirs


def test_python_imports_and_definitions_become_links_without_anyone_writing_them(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "clock.py").write_text('"""The clock."""\n\nclass Clock:\n    pass\n')
    (tmp_path / "app" / "timers.py").write_text("from app.clock import Clock\n\ndef make():\n    return Clock()\n")
    (tmp_path / "app" / "broken.py").write_text("def (:\n")
    team = TeamMemory()
    assert team.ingest_codemap(tmp_path) == 3
    assert ("file:app/timers.py", "imports", "file:app/clock.py") in {(e.src, e.rel, e.dst) for e in team.project.edges()}
    assert "defines Clock" in team.project.get("file:app/clock.py").text
    assert [h.node.name for h in team.search("project", "what uses the clock", k=3)][:2] == ["app/clock.py", "app/timers.py"]


def test_finished_tasks_decisions_and_conflicts_are_noticed():
    team = TeamMemory()
    team.ingest_task("DEV_2", "timer-plugin", "Develop TimerPlugin", ["jarvis/plugins/timer/timer_plugin.py"], "Registry and expiry done.")
    team.ingest_task("DEV_3", "router", "Implement TimerRouter", ["jarvis/plugins/router/rule_router.py"], "Gave up: the grammar clashed.", ok=False)
    team.ingest_decision("Use a Clock protocol", True, "DEV_1", "tests must not sleep", "add Clock to contracts.py")
    team.ingest_conflict("router", ["jarvis/plugins/router/rule_router.py"], resolved=True, dev="DEV_3")
    edges = {(e.src, e.rel, e.dst) for e in team.project.edges()}
    assert ("task:timer-plugin: Develop TimerPlugin", "done_by", "agent:DEV_2") in edges and ("task:router: Implement TimerRouter", "struggled_with_by", "agent:DEV_3") in edges
    assert "Gave up" in team.recall_sync("DEV_3", "router grammar") and "merge conflict" in team.recall_sync("DEV_2", "rule_router conflict")
    assert "# Team memory" in team.report() and "Use a Clock protocol" in team.report()


# ---------------------------------------------------------------------------------------------- writing with a model

def test_a_model_turns_an_event_into_memories_and_each_is_checked_against_what_is_known():
    model = FakeModel([
        {"memories": [
            {"kind": "convention", "name": "inject time", "text": "Take a Clock; never call time.monotonic().", "importance": 8, "tags": ["testing"], "scope": "project",
             "links": [{"relation": "about", "kind": "file", "name": "contracts.py"}]},
            {"kind": "preference", "name": "my testing habit", "text": "I write the test first.", "importance": 3, "scope": "agent"},
        ]},
    ])
    team = TeamMemory(model=model)
    done = team.learn_sync(X.Event("task_done", "DEV_1", "core-contracts: Define Clock", "Added Clock and FakeClock to contracts.py", "core-contracts", ["jarvis/core/contracts.py"]))
    assert done == {"add": 2}
    assert team.project.get("convention:inject time").importance == 8 and team.agent("DEV_1").get("preference:my testing habit")
    assert ("convention:inject time", "about", "file:contracts.py") in {(e.src, e.rel, e.dst) for e in team.project.edges()}
    assert team.project.get("preference:my testing habit") is None  # private stays private

    # the same knowledge arrives again from another agent: the model says the team already knows it
    team.model = FakeModel([{"memories": [{"kind": "convention", "name": "use a clock", "text": "Always inject a Clock; never read the real time.", "importance": 6, "scope": "project"}]},
                            {"op": "NOOP", "target": 0, "text": ""}])
    team._retrievers.clear()
    assert team.learn_sync(X.Event("task_done", "DEV_2", "t", "x")) == {"noop": 1}
    assert team.project.get("convention:inject time").mentions == 2 and team.project.get("convention:use a clock") is None

    # a fact that stopped being true is replaced, not erased
    team.model = FakeModel([{"memories": [{"kind": "convention", "name": "time via clock module", "text": "The Clock now lives in jarvis/core/clock.py; take a Clock from there.", "importance": 8, "scope": "project"}]},
                            {"op": "SUPERSEDE", "target": 0, "text": ""}])
    team._retrievers.clear()
    assert team.learn_sync(X.Event("task_done", "DEV_1", "move clock", "moved")) == {"supersede": 1}
    assert team.project.get("convention:inject time").valid_to is not None and "time via clock module" in [n.name for n in team.project.nodes()]


def test_without_a_model_the_events_that_always_matter_are_still_remembered():
    team = TeamMemory()
    assert team.learn_sync(X.Event("conflict", "DEV_3", "merge conflict in rule_router.py", "both branches changed the grammar", "router")) == {"add": 1}
    assert team.learn_sync(X.Event("task_done", "DEV_3", "fine", "all good")) == {}


def test_reflection_writes_insights_linked_to_their_evidence():
    g = MemoryGraph()
    for i in range(7):
        g.node("pitfall", f"flaky sleep {i}", "A test used a real sleep and failed on CI.", "DEV_1", [], 6)
    model = FakeModel([{"insights": [{"name": "never sleep in tests", "text": "Every flaky test so far used a real sleep.", "importance": 8, "evidence": [0, 1, 2]},
                                      {"name": "no evidence", "text": "x", "evidence": []}]}])
    made = X.reflect(g, model, "team")
    assert [n.name for n in made] == ["never sleep in tests"]
    assert len([e for e in g.edges() if e.rel == "supports"]) == 3
    assert X.reflect(g, None, "team") == [] and X.reflect(MemoryGraph(), model, "team") == []
