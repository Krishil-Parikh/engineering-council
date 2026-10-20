"""The small commits a developer's work is saved in: what their messages say."""

from team.checkpoint import build_message, classify, parse_name_status, scope_of


def changes(*pairs):
    return list(pairs)


def test_name_status_output_is_parsed_including_renames():
    text = "A\tjarvis/core/contracts.py\nM\tjarvis/core/bus.py\nR100\told.py\tjarvis/plugins/timer/registry.py\nD\tnotes.txt"
    assert parse_name_status(text) == [("A", "jarvis/core/contracts.py"), ("M", "jarvis/core/bus.py"), ("R", "jarvis/plugins/timer/registry.py"), ("D", "notes.txt")]


def test_tests_docs_config_fixes_and_features_are_told_apart():
    assert classify(["tests/test_timer.py", "tests/conftest.py"]) == "test"
    assert classify(["README.md", "docs/Design.md"]) == "docs"
    assert classify([".env.example", "pyproject.toml"]) == "chore"
    assert classify(["jarvis/core/bus.py"], "Fixed the off-by-one in the queue") == "fix"
    assert classify(["jarvis/core/bus.py", "tests/test_bus.py"]) == "feat"


def test_the_scope_is_the_part_of_the_project_not_a_layout_folder():
    assert scope_of(["jarvis/plugins/timer/timer_plugin.py", "jarvis/plugins/timer/__init__.py"]) == "timer"
    assert scope_of(["jarvis/core/contracts.py"], "foundation") == "core"
    assert scope_of(["tests/test_timer_plugin.py"]) == "timer"
    assert scope_of(["main.py"], "app-loop") == "app-loop"


def test_a_message_says_what_was_added_and_what_was_updated():
    subject, body = build_message(changes(("A", "jarvis/plugins/timer/registry.py"), ("A", "jarvis/plugins/timer/expiry.py"), ("M", "jarvis/core/contracts.py")),
                                  feature="timer-plugin-logic", task="Develop TimerPlugin", note="Added the registry and wired the clock in.")
    assert subject == "feat(timer): add registry.py, expiry.py; update contracts.py"
    assert "Task: Develop TimerPlugin" in body and "Feature: timer-plugin-logic" in body and "add: jarvis/plugins/timer/registry.py" in body
    assert "Added the registry and wired the clock in." in body


def test_a_test_only_change_is_a_test_commit():
    subject, _ = build_message(changes(("A", "tests/test_registry.py")), feature="f")
    assert subject == "test(registry): add test_registry.py"


def test_a_long_list_of_files_stays_within_the_subject_limit():
    many = [("A", f"jarvis/plugins/timer/very_long_module_name_number_{n}.py") for n in range(12)]
    subject, body = build_message(many, feature="f")
    assert len(subject) <= 72 and subject.startswith("feat(timer): add very_long_module_name_number_0.py")
    assert "and 11 more" in subject and "... and" not in body.splitlines()[-1] or "more files" in body


def test_nothing_changed_means_no_commit():
    assert build_message([]) is None
