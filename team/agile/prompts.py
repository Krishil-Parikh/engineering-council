"""What the scrum master and the developers are asked in each ceremony. Every JSON-answer prompt says so plainly and names its keys.

The facts in a prompt come from git, the plan and the recorded task log, not from anyone's memory: the model is asked to talk about them,
not to invent them."""

from __future__ import annotations

import json
import re
from typing import Any

JSON_ONLY = "Respond only with a JSON object, no prose and no markdown fences."


def extract_json(text: str) -> Any:
    """The first JSON object in a model's answer, or None."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


# ---------------------------------------------------------------------------- planning

PLANNING_PROMPT = """SPRINT PLANNING for sprint {number}. You are the scrum master. Pick the work for this sprint from the product backlog.

SPRINT CAPACITY: about {capacity} tasks (a feature costs as many tasks as it lists). {carried}
Features already in progress from the last sprint are not listed again; they use part of the capacity.

PRODUCT BACKLOG (in priority order; "after" means it cannot start before those features are merged)
{backlog}

THE TEAM'S IMPEDIMENTS STILL OPEN
{impediments}

THE HUMAN'S STANDING INSTRUCTIONS
{directives}

Choose features that fit the capacity, respect the dependencies (a feature may be chosen if everything it is "after" is already merged or also chosen), and give the developers parallel work. Write ONE sentence as the sprint goal: what the product can do at the end of the sprint that it cannot do now.
{json_only}
{{"goal": "...", "features": ["feature-id", "..."], "rationale": "one or two sentences"}}"""

COMMITMENT_PROMPT = """SPRINT PLANNING, sprint {number}. The scrum master proposes this sprint.

GOAL: {goal}
YOUR FEATURES: {mine}
EVERYONE'S FEATURES
{everyone}

As {dev}, can you commit to your part within the sprint? Say what worries you (a missing interface, a dependency on a teammate, an unclear requirement) and what you need before you start.
{json_only}
{{"commit": true or false, "concerns": "one or two sentences, or an empty string"}}"""

# ---------------------------------------------------------------------------- standup

STANDUP_PROMPT = """DAILY STANDUP, sprint {sprint}, day {day}. Coding is paused while the team meets. You are {dev}.

FACTS ABOUT YOUR DAY (from the task log and git)
{facts}

Answer the three standup questions briefly and truthfully from those facts: what you did since the last standup, what you will do next, and what blocks you (anything you need from a teammate or the human; say "none" if nothing).
{json_only}
{{"done": "...", "next": "...", "blockers": "..."}}"""

STANDUP_SUMMARY_PROMPT = """DAILY STANDUP SUMMARY, sprint {sprint}, day {day}. You are the scrum master. Sprint goal: {goal}

SPRINT PROGRESS: {progress}

WHAT EACH DEVELOPER SAID
{entries}

OPEN IMPEDIMENTS
{impediments}

Write a two- or three-sentence summary of where the sprint stands. For every impediment that someone could resolve right now, give the resolution as an instruction to the developer who is blocked (what they should do, or what a teammate will provide). Leave an impediment unresolved if it needs the human.
{json_only}
{{"summary": "...", "resolutions": [{{"impediment": "IMP-001", "resolved": true or false, "instruction": "what the blocked developer should do next"}}]}}"""

# ---------------------------------------------------------------------------- review

REVIEW_DEMO_PROMPT = """SPRINT REVIEW, sprint {number}. You are {dev}. Sprint goal: {goal}

YOUR FEATURES AND HOW THEY ENDED
{mine}

Give your demo in a few sentences: what now works that did not before, what is still missing, and anything the team should know before relying on it.
{json_only}
{{"demo": "...", "missing": "...", "warning": "..."}}"""

REVIEW_PROMPT = """SPRINT REVIEW, sprint {number}. You are the scrum master. Sprint goal: {goal}

OUTCOME BY FEATURE
{features}

TEST AND VERIFICATION RESULTS ON THE INTEGRATION BRANCH
{verification}

WHAT THE DEVELOPERS DEMONSTRATED
{demos}

Decide whether the sprint goal was met, summarize the increment in a short paragraph, and list what carries over and why.
{json_only}
{{"goal_met": true or false, "summary": "...", "carry_over": [{{"feature": "id", "why": "..."}}]}}"""

# ---------------------------------------------------------------------------- reports and retrospective

REPORT_NARRATIVE_PROMPT = """SPRINT REPORT, sprint {number}. You are the scrum master writing the narrative for the sprint report.

NUMBERS
{numbers}

STANDUP SUMMARIES
{standups}

Write one short paragraph (at most 6 sentences) for the stakeholders: what was delivered, what slipped and why, and how the team is trending. Stick to the numbers above.
{json_only}
{{"narrative": "..."}}"""

RETRO_PROMPT = """SPRINT RETROSPECTIVE, sprint {number}. You are {dev}. The sprint is over; the team looks back to work better.

WHAT HAPPENED
{facts}

Say what went well, what went badly, and ONE concrete change the team should make next sprint (specific enough to act on: "agree interfaces before splitting a feature", not "communicate more").
{json_only}
{{"went_well": "...", "went_badly": "...", "change": "..."}}"""

RETRO_SUMMARY_PROMPT = """SPRINT RETROSPECTIVE, sprint {number}. You are the scrum master. Combine what the developers said.

{entries}

Pick at most three actions for the next sprint, each with an owner (a developer name, or "team"). Keep the ones that would have prevented a real problem seen this sprint. Also give one lesson for the team's long-term memory in a sentence.
{json_only}
{{"went_well": ["..."], "went_badly": ["..."], "actions": [{{"action": "...", "owner": "name or team"}}], "lesson": "..."}}"""

# ---------------------------------------------------------------------------- documents

DOCSYNC_PROMPT = """DOCUMENT SYNC after sprint {number}. You are the scrum master. Coding is paused. Decide whether the project documents still describe what the team is building.

WHAT CHANGED THIS SPRINT
{changes}

DECISIONS TAKEN (design votes, the human's instructions)
{decisions}

THE DOCUMENTS: docs/PRD.md (what and why), docs/Technical_Approach.md (how), docs/Design.md (components and contracts)

List the amendments that are needed, if any. Mark an amendment "major" when it changes scope (adds or removes a requirement or feature), the architecture, the tech stack, a public contract or a data model; the human must approve those. Mark it routine when it only brings the text in line with what was built (a renamed file, a clarified step, a corrected detail).
{json_only}
{{"amendments": [{{"doc": "PRD.md" | "Technical_Approach.md" | "Design.md", "change": "exactly what to change", "why": "...", "major": true or false}}]}}"""

APPLY_DOCS_PROMPT = """You are updating the project documents in docs/ after a sprint. Apply exactly these amendments, nothing else, and keep each document's structure and tone. Edit the files in place.

{amendments}

When you are done, reply with one line per file you changed."""

REVISE_DOCS_PROMPT = """The human reviewed the project documents (docs/PRD.md, docs/Technical_Approach.md, docs/Design.md) before development and asked for changes. Edit the documents so they reflect the feedback; keep what the feedback does not touch. Edit the files in place.

THE HUMAN'S FEEDBACK
{feedback}

When you are done, reply with one line per file you changed."""

# ---------------------------------------------------------------------------- the human

CLASSIFY_PROMPT = """The human supervising this project interrupted the team and said:

"{text}"

You are the scrum master. Classify it.
  note   - guidance for how to work or build (a preference, a correction, a constraint) that does not change what is being built
  scope  - changes WHAT is built: add, drop or reprioritize features or requirements
  rethink - says the team is going in the wrong direction and needs to stop and reconsider the approach
{json_only}
{{"kind": "note" | "scope" | "rethink", "summary": "one sentence restating it as an instruction to the team"}}"""

REPLAN_PROMPT = """EMERGENCY REPLANNING. You are the scrum master. The human changed the scope of the project:

"{text}"

CURRENT BACKLOG AND PROGRESS
{backlog}

Decide what changes: features to drop, features to add (with tasks), and the new priority order of the unfinished features. Never drop a feature that is already merged. New features need a short kebab-case id, an owner from {team} (or null), the ids they depend on, and 1 to 4 tasks.
{json_only}
{{"drop": ["feature-id"], "add": [{{"id": "...", "title": "...", "summary": "...", "owner": null, "depends_on": [], "tasks": [{{"title": "...", "details": "..."}}]}}], "priority": ["feature-id"], "docs": "which documents need to change and how, or an empty string", "rationale": "..."}}"""

RETHINK_PROMPT = """STOP AND RETHINK. The human supervising this project said the team is going the wrong way:

"{text}"

SPRINT {sprint} GOAL: {goal}
PROGRESS: {progress}

Each of you, from your own area: what exactly is wrong with the current direction in the human's view, and what should change? Be concrete (which feature, contract or decision) and brief."""

RETHINK_SUMMARY_PROMPT = """STOP AND RETHINK, scrum master's conclusion. The human said:

"{text}"

The developers said:
{entries}

Propose the course correction as JSON: which features to drop or change, what to tell the team to do differently, and which documents change.
{json_only}
{{"summary": "...", "drop": ["feature-id"], "instruction": "what every developer must do differently from now on", "docs": "document changes needed, or an empty string"}}"""
