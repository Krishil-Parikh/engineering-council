"""Staffing the pod: only the skills the problem needs get seats, skills are not exclusive, preferences are honoured."""

from collections import Counter

from meetings import prompts
from meetings.conversation import assign_skills, needed_skills
from meetings.formatting import format_blind
from meetings.models import AGENT_IDS, SKILLS, BlindThoughts

AGENTS = list(AGENT_IDS)


def blinds(needed_by_dev: dict[str, list[str]], prefs: dict[str, list[str]] | None = None):
    return {a: BlindThoughts(agent_id=a, understanding="u", skills_needed=needed_by_dev.get(a, []), skill_preferences=(prefs or {}).get(a, [])) for a in AGENTS}


def test_nobody_answering_staffs_every_skill_as_before():
    b = blinds({})
    assert needed_skills(b, AGENTS) == list(SKILLS)
    assert sorted(assign_skills(b, AGENTS).values()) == sorted(SKILLS)


def test_a_skill_nobody_named_gets_no_developer():
    same = {a: ["backend", "database", "devops"] for a in AGENTS}
    roster = assign_skills(blinds(same), AGENTS)
    assert set(roster.values()) == {"BACKEND", "DATABASE", "DEVOPS"} and len(roster) == 6
    assert not {"AIML", "MLOPS", "FRONTEND"} & set(roster.values())
    assert Counter(roster.values()) == Counter({"BACKEND": 2, "DATABASE": 2, "DEVOPS": 2})  # equally named, equally staffed


def test_heavier_skills_get_more_developers_and_every_needed_skill_gets_at_least_one():
    named = {"DEV_1": ["backend"], "DEV_2": ["backend", "frontend"], "DEV_3": ["backend"], "DEV_4": ["backend", "database"], "DEV_5": ["backend"], "DEV_6": ["backend", "frontend"]}
    b = blinds(named)
    assert needed_skills(b, AGENTS) == ["BACKEND", "FRONTEND"]  # database was named once of six: below a third
    counts = Counter(assign_skills(b, AGENTS).values())
    assert counts["BACKEND"] > counts["FRONTEND"] >= 1 and sum(counts.values()) == 6


def test_the_two_most_named_skills_are_kept_even_when_few_agree():
    scattered = {"DEV_1": ["backend"], "DEV_2": ["frontend"], "DEV_3": ["aiml"], "DEV_4": ["mlops"], "DEV_5": ["devops"], "DEV_6": ["database"]}
    assert needed_skills(blinds(scattered), AGENTS) == ["FRONTEND", "BACKEND"]  # one vote each is below the threshold of two; ties keep the standard order
    one = {a: ["backend"] for a in AGENTS}
    assert needed_skills(blinds(one), AGENTS) == ["BACKEND"]  # everyone agrees, so only one skill exists to staff
    assert set(assign_skills(blinds(one), AGENTS).values()) == {"BACKEND"}


def test_preferences_decide_who_takes_which_needed_skill():
    needed = {a: ["backend", "frontend", "database"] for a in AGENTS}
    prefs = {"DEV_1": ["database"], "DEV_2": ["frontend"], "DEV_3": ["backend"], "DEV_4": ["backend"]}
    roster = assign_skills(blinds(needed, prefs), AGENTS)
    assert roster["DEV_1"] == "DATABASE" and roster["DEV_2"] == "FRONTEND" and roster["DEV_3"] == "BACKEND"
    assert roster["DEV_4"] == "BACKEND"  # a second seat on the skill the work leans on
    assert set(roster.values()) == {"BACKEND", "FRONTEND", "DATABASE"}


def test_a_preference_for_a_skill_the_problem_does_not_need_is_ignored():
    needed = {a: ["backend", "database"] for a in AGENTS}
    prefs = {"DEV_1": ["aiml", "mlops"], "DEV_2": ["database"]}
    roster = assign_skills(blinds(needed, prefs), AGENTS)
    assert set(roster.values()) == {"BACKEND", "DATABASE"} and roster["DEV_2"] == "DATABASE"


def test_aliases_and_junk_in_the_answers_are_tolerated():
    named = {a: ["Back End", "DB", "nonsense", "backend"] for a in AGENTS}
    b = blinds(named)
    assert needed_skills(b, AGENTS) == ["BACKEND", "DATABASE"]
    assert set(assign_skills(b, AGENTS).values()) == {"BACKEND", "DATABASE"}


def test_more_needed_skills_than_developers_staffs_the_most_named():
    named = {a: ["backend", "frontend", "database", "devops", "aiml", "mlops"] for a in AGENTS[:3]}
    roster = assign_skills(blinds(named), AGENTS[:3])
    assert len(roster) == 3 and len(set(roster.values())) == 3


def test_every_developer_is_staffed_and_order_is_stable():
    named = {a: ["backend", "frontend"] for a in AGENTS}
    first = assign_skills(blinds(named), AGENTS)
    assert list(first) == AGENTS and first == assign_skills(blinds(named), AGENTS)


def test_the_blind_prompt_asks_for_needed_skills_and_the_notes_show_them():
    prompt = prompts.blind_prompt("DEV_1", "context")
    assert "skills_needed" in prompt and "Leave out a skill if the project would not miss it" in prompt
    shown = format_blind(BlindThoughts(agent_id="DEV_1", understanding="u", skills_needed=["BACKEND"], skill_preferences=["BACKEND"]))
    assert "SKILLS THE PROBLEM NEEDS" in shown and "BACKEND" in shown
