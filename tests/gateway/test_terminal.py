"""Each agent's live terminal: its tool calls and output, as lines, newest last."""

from types import SimpleNamespace

from gateway.bridges import TeamBridge
from gateway.narrator import Narrator
from gateway.projection import Projection
from gateway.terminal import AgentTerminals, describe_call


def feed(terminals, who, *events):
    last = None
    for event, data in events:
        last = terminals.feed(who, event, data) or last
    return last


def test_a_shell_command_and_its_result_read_like_a_terminal():
    lines = feed(
        AgentTerminals(), "DEV_2",
        ("tool.input.started", {"call": "c1", "tool": "shell"}),
        ("tool.called", {"call": "c1", "input": {"command": "pytest -q tests/test_timer.py"}}),
        ("tool.success", {"call": "c1"}),
        ("shell.exited", {"id": "sh1", "exit": 0, "status": "done"}),
    )
    assert [line.split(" ", 1)[1] for line in lines] == ["$ pytest -q tests/test_timer.py", "  exit 0"]


def test_reads_searches_edits_failures_and_model_text_each_get_a_line():
    t = AgentTerminals()
    feed(t, "DEV_1", ("tool.input.started", {"call": "a", "tool": "read"}), ("tool.called", {"call": "a", "input": {"path": "jarvis/core/contracts.py", "startingLine": 40}}))
    feed(t, "DEV_1", ("tool.input.started", {"call": "b", "tool": "glob"}), ("tool.called", {"call": "b", "input": {"pattern": "tests/*.py"}}))
    feed(t, "DEV_1", ("tool.input.started", {"call": "c", "tool": "write"}), ("tool.called", {"call": "c", "input": {"path": "jarvis/plugins/timer/timer_plugin.py"}}))
    feed(t, "DEV_1", ("tool.failed", {"call": "a", "error": "File not found: jarvis/core/protocols.py"}))
    lines = feed(t, "DEV_1", ("text.ended", {"text": "I will register the plugin next."}))
    bodies = [line.split(" ", 1)[1] for line in lines]
    assert bodies == [
        "read jarvis/core/contracts.py:40", "glob tests/*.py", "write jarvis/plugins/timer/timer_plugin.py",
        "! File not found: jarvis/core/protocols.py", "# I will register the plugin next.",
    ]


def test_only_the_most_recent_lines_are_kept_per_agent_and_agents_do_not_mix():
    t = AgentTerminals(keep=5)
    for n in range(12):
        feed(t, "DEV_1", ("tool.input.started", {"call": f"c{n}", "tool": "shell"}), ("tool.called", {"call": f"c{n}", "input": {"command": f"echo {n}"}}))
    feed(t, "DEV_2", ("tool.input.started", {"call": "x", "tool": "shell"}), ("tool.called", {"call": "x", "input": {"command": "ls"}}))
    assert [line.split(" ", 1)[1] for line in t.lines["agent-01"]] == [f"$ echo {n}" for n in range(7, 12)]
    assert len(t.lines["agent-02"]) == 1


def test_events_that_say_nothing_new_add_no_line():
    t = AgentTerminals()
    assert t.feed("DEV_1", "step.started", {}) is None
    assert t.feed("DEV_1", "tool.success", {"call": "z"}) is None
    assert t.feed("DEV_1", "idle", {"outcome": "succeeded"}) is None
    assert describe_call("mystery", {"input": {"a": 1}}).startswith("mystery")


def test_the_team_bridge_puts_the_terminal_on_the_agent_in_the_snapshot():
    projection = Projection("workspace-demo")
    narrator = Narrator(projection)
    run = SimpleNamespace(narrator=narrator, terminals=AgentTerminals())
    bridge = TeamBridge(run)
    bridge.handle("DEV_3:tool.input.started", {"call": "k", "tool": "shell"})
    bridge.handle("DEV_3:tool.called", {"call": "k", "input": {"command": "git status"}})
    bridge.handle("integrator:text.ended", {"text": "Merging feature/timers."})
    agents = {a["id"]: a for a in projection.snapshot()["agents"]}
    assert agents["agent-03"]["terminal"][-1].endswith("$ git status")
    assert agents["agent-sm"]["terminal"][-1].endswith("# Merging feature/timers.")  # the integrator's work shows on the scrum master
