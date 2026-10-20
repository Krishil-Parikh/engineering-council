"""Writing memory: a model turns what just happened into memories, and decides what each one means for what is already known.

  extract     what happened (a finished task, a merged feature, a design decision, a conflict, a retrospective) -> atomic memories: a kind, a name, a sentence or two, how
              much it matters (1-10), tags, and what it is linked to
  reconcile   for each one, look at the closest existing memories and decide, like Mem0: ADD it, UPDATE what is there, SUPERSEDE a fact that is no longer true (the old one
              keeps its validity window), or NOOP because the team already knows it
  reflect     now and then, read the recent memories and write the few higher-level insights they support (Generative Agents / A-MEM), linked back to their evidence

With no model every function still works in a plain way (a memory is added; the same name is merged), so memory never blocks the build."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from memory.graph import MemoryGraph, Node, node_id
from memory.models import MemoryModel
from memory.retrieval import Query, Retriever

KINDS = ("note", "convention", "api", "pitfall", "how-to", "decision", "insight", "preference")


@dataclass
class Event:
    kind: str  # task_done | task_failed | feature_merged | design_decision | conflict | retrospective | code_change
    author: str
    title: str
    text: str = ""
    feature: str = ""
    files: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    kind: str
    name: str
    text: str
    importance: float = 5.0
    tags: list[str] = field(default_factory=list)
    scope: str = "project"  # project | agent
    links: list[tuple[str, str, str]] = field(default_factory=list)  # (relation, kind, name)


EXTRACT_PROMPT = """You maintain the long-term memory of a software engineering team. Something just happened. Write down what the team (and this developer) should remember
to work faster and better later: conventions to follow, APIs and what they promise, how something works, traps and how they were avoided, decisions and why, what worked.

Event: {kind}
Developer: {author}
Feature: {feature}
Title: {title}
Files involved: {files}
What happened:
{text}

Rules:
- Each memory is ONE atomic fact in one or two sentences, specific (name the file, function, command), true as written, useful to someone who was not there.
- Do not record trivia, or what is obvious from the code itself.
- "scope": "project" if any teammate could use it; "agent" if it is only about this developer's own habits, mistakes or preferences.
- "importance": 1 (minor) to 10 (the team must not forget this).
- "links": what it is about, as {{"relation": "about|imports|depends_on|affects|fixes|replaces|part_of", "kind": "file|module|feature|decision|api|note", "name": "..."}}.

Return JSON: {{"memories": [{{"kind": "note|convention|api|pitfall|how-to|decision|preference", "name": "short searchable name", "text": "...", "importance": 5, "tags": ["..."], "scope": "project", "links": []}}]}}
Return {{"memories": []}} when nothing is worth keeping."""

RECONCILE_PROMPT = """A team's memory is being updated. A NEW memory has been proposed. Compare it with the EXISTING memories that are closest and decide.

NEW: [{kind}] {name}: {text}

EXISTING:
{existing}

Decide ONE:
- "ADD": it is new knowledge.
- "UPDATE": it refines or extends existing memory number N; give "text", the merged memory in one or two sentences.
- "SUPERSEDE": existing memory N is no longer true (the new one replaces it).
- "NOOP": the team already knows this (existing memory N says it).

Return JSON: {{"op": "ADD|UPDATE|SUPERSEDE|NOOP", "target": N or null, "text": "merged text for UPDATE, else empty"}}"""

REFLECT_PROMPT = """Read these recent memories of a software team and write the {limit} most useful higher-level insights they support: patterns, recurring trouble, working agreements, what to do differently.
Each insight must be supported by the memories it cites (by number).

Memories:
{memories}

Return JSON: {{"insights": [{{"name": "short name", "text": "one or two sentences", "importance": 6, "evidence": [numbers]}}]}} (an empty list when there is no pattern yet)."""


def _clean_kind(kind: str) -> str:
    kind = re.sub(r"[^a-z-]", "", str(kind).lower())
    return kind if kind in KINDS else "note"


def extract(model: Optional[MemoryModel], event: Event) -> list[Candidate]:
    """The memories worth keeping from an event. Without a model, one plain memory for the events that always matter."""
    if model is None:
        if event.kind in ("conflict", "task_failed", "design_decision"):
            kind = "decision" if event.kind == "design_decision" else "pitfall"
            return [Candidate(kind, event.title, event.text[:400], 6.0, [event.kind], "project", [("about", "feature", event.feature)] if event.feature else [])]
        return []
    try:
        reply = model.generate_json(EXTRACT_PROMPT.format(kind=event.kind, author=event.author, feature=event.feature or "-", title=event.title, files=", ".join(event.files[:20]) or "-", text=event.text[:6000]))
    except Exception:  # noqa: BLE001
        return []
    found: list[Candidate] = []
    for m in (reply.get("memories") if isinstance(reply, dict) else None) or []:
        if not isinstance(m, dict) or not str(m.get("name", "")).strip() or not str(m.get("text", "")).strip():
            continue
        links = [(str(l.get("relation", "about")), str(l.get("kind", "note")), str(l.get("name", ""))) for l in (m.get("links") or []) if isinstance(l, dict) and l.get("name")]
        try:
            importance = max(1.0, min(10.0, float(m.get("importance", 5))))
        except (TypeError, ValueError):
            importance = 5.0
        found.append(Candidate(_clean_kind(m.get("kind", "note")), str(m["name"]).strip()[:120], str(m["text"]).strip(), importance,
                               [str(t) for t in (m.get("tags") or [])][:8], "agent" if m.get("scope") == "agent" else "project", links[:8]))
    return found[:8]


def resolve(graph: MemoryGraph, kind: str, name: str) -> tuple[str, str]:
    """The thing a link points to: an existing memory with that name (any case, with or without its folder) rather than a duplicate under a slightly different spelling."""
    key = re.sub(r"\W+", " ", name.lower()).strip()
    base = key.split(" ")[-2:] if "/" in name else None
    best: Optional[Node] = None
    for n in graph.nodes():
        nkey = re.sub(r"\W+", " ", n.name.lower()).strip()
        if nkey == key:
            return n.kind, n.name
        if kind == n.kind == "file" and base and nkey.endswith(" ".join(base)):
            best = best or n
    return (best.kind, best.name) if best else (kind, name)


def apply(graph: MemoryGraph, retriever: Retriever, model: Optional[MemoryModel], cand: Candidate, owner: str) -> str:
    """Puts a proposed memory into a graph after looking at what is already there. Returns what was done: add, update, supersede or noop."""
    existing_id = node_id(cand.kind, cand.name)
    op, target = "add", None
    similar = [h for h in retriever.search(Query(f"{cand.name} {cand.text}"), k=5, kinds=[k for k in KINDS if k != "insight"]) if h.signals.get("via") == "match"][:4]
    if graph.get(existing_id) is not None:
        op, target = "update", graph.get(existing_id)
    elif similar and model is not None:
        listing = "\n".join(f"{i}. [{h.node.kind}] {h.node.name}: {h.node.text[:300]}" for i, h in enumerate(similar))
        try:
            reply = model.generate_json(RECONCILE_PROMPT.format(kind=cand.kind, name=cand.name, text=cand.text, existing=listing))
            wanted = str(reply.get("op", "ADD")).upper() if isinstance(reply, dict) else "ADD"
            index = reply.get("target") if isinstance(reply, dict) else None
            if wanted in ("UPDATE", "SUPERSEDE", "NOOP") and isinstance(index, int) and 0 <= index < len(similar):
                op, target = wanted.lower(), similar[index].node
                if op == "update" and reply.get("text"):
                    cand.text = str(reply["text"])
        except Exception:  # noqa: BLE001 - when in doubt, add: a duplicate is cheaper than a lost memory
            op = "add"
    if op == "noop" and target is not None:
        graph.node(target.kind, target.name)  # it was mentioned again: it matters a little more
        return "noop"
    if op == "update" and target is not None:
        graph.node(target.kind, target.name, cand.text, owner, cand.tags, cand.importance)
        written = target
    else:
        written = graph.node(cand.kind, cand.name, cand.text, owner, cand.tags, cand.importance)
        if op == "supersede" and target is not None:
            graph.supersede(target.id, written.id, f"replaced by: {cand.text[:120]}")
    for rel, kind, name in cand.links:
        if not name.strip():
            continue
        rk, rn = resolve(graph, kind, name)
        graph.link((written.kind, written.name), rel, (rk, rn), owner=owner)
    return op


def reflect(graph: MemoryGraph, model: Optional[MemoryModel], owner: str, limit: int = 4, recent: int = 40) -> list[Node]:
    """Writes the higher-level insights the recent memories support, linked to their evidence. No model, no insights (they are not worth inventing)."""
    if model is None:
        return []
    pool = [n for n in graph.nodes() if n.kind in ("note", "convention", "api", "pitfall", "how-to", "decision", "preference", "task")]
    pool = sorted(pool, key=lambda n: -n.updated)[:recent]
    if len(pool) < 6:
        return []
    listing = "\n".join(f"{i}. [{n.kind}] {n.name}: {n.text[:220]}" for i, n in enumerate(pool))
    try:
        reply = model.generate_json(REFLECT_PROMPT.format(limit=limit, memories=listing))
    except Exception:  # noqa: BLE001
        return []
    made: list[Node] = []
    for item in (reply.get("insights") if isinstance(reply, dict) else None) or []:
        if not isinstance(item, dict) or not item.get("name") or not item.get("text"):
            continue
        evidence = [pool[i] for i in (item.get("evidence") or []) if isinstance(i, int) and 0 <= i < len(pool)]
        if not evidence:
            continue
        try:
            importance = max(1.0, min(10.0, float(item.get("importance", 6))))
        except (TypeError, ValueError):
            importance = 6.0
        node = graph.node("insight", str(item["name"])[:120], str(item["text"]), owner, ["reflection"], importance)
        for ev in evidence:
            graph.link((ev.kind, ev.name), "supports", (node.kind, node.name), owner=owner)
        made.append(node)
    return made
