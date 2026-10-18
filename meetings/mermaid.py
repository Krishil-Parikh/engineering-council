"""Mermaid helpers: clean and lint diagrams the model wrote, and build safe fallbacks from the spec in Python."""

from __future__ import annotations

import re

KINDS = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram-v2", "stateDiagram", "erDiagram", "journey", "gantt",
)
_FENCE = re.compile(r"^\s*```(?:mermaid)?\s*|\s*```\s*$", re.IGNORECASE)
BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def clean(diagram: str) -> str:
    """Strip code fences the model may have wrapped around the diagram."""
    return _FENCE.sub("", (diagram or "").strip()).strip()


def lint(diagram: str) -> list[str]:
    """Cheap structural checks. They catch the mistakes that break rendering most often; they do not replace a renderer."""
    d = clean(diagram)
    if not d:
        return ["diagram is empty"]
    lines = [ln for ln in d.splitlines() if ln.strip() and not ln.strip().startswith("%%")]
    if not lines or not lines[0].strip().startswith(KINDS):
        return [f"first line must start with a diagram type ({', '.join(KINDS[:4])}...), got {lines[0].strip()[:30]!r}" if lines else "diagram is empty"]
    problems: list[str] = []
    if len(lines) < 2:
        problems.append("diagram has a header but no content")
    body = "\n".join(lines[1:])
    for open_, close in (("[", "]"), ("(", ")"), ("{", "}")):
        if body.count(open_) != body.count(close) and not lines[0].startswith(("sequenceDiagram", "erDiagram", "journey")):
            problems.append(f"unbalanced {open_}{close}")
    if body.count('"') % 2:
        problems.append("unbalanced double quotes")
    if lines[0].startswith(("flowchart", "graph")):
        if not re.search(r"-->|---|==>|-\.->|-\.-", body):
            problems.append("flowchart has no edges")
        if re.search(r"\b(end|subgraph)\b\s*$", lines[-1]) is None and body.count("subgraph") != len(re.findall(r"^\s*end\s*$", body, re.M)):
            problems.append("subgraph/end mismatch")
    if lines[0].startswith("sequenceDiagram") and not re.search(r"->>|-->>|->|-->|-x|--x", body):
        problems.append("sequence diagram has no messages")
    if lines[0].startswith("erDiagram") and not re.search(r"\|\||o\{|\}o|\}\||\|o|\{", body):
        problems.append("erDiagram has no relationships or entities")
    return problems


def fence(diagram: str) -> str:
    return f"```mermaid\n{clean(diagram)}\n```\n"


def mentions(diagram: str, names: list[str]) -> list[str]:
    """Names that do not appear anywhere in the diagram text."""
    low = clean(diagram).lower()
    return [n for n in names if n.lower() not in low]


def _id(name: str, used: dict[str, str]) -> str:
    if name in used:
        return used[name]
    base = re.sub(r"[^A-Za-z0-9]", "", name.title()) or "N"
    if base[0].isdigit():
        base = "N" + base
    cand, i = base, 2
    while cand in used.values() or cand.lower() in {"end", "graph", "flowchart", "subgraph"}:
        cand, i = f"{base}{i}", i + 1
    used[name] = cand
    return cand


def _label(text: str) -> str:
    return re.sub(r'["\[\]{}()<>|`]', "", text).strip()[:60] or "item"


def architecture_fallback(components: list, tech_choices: list | None = None) -> str:
    """components: objects with .name/.path/.depends_on. Dependency direction is an arrow from user to dependency."""
    used: dict[str, str] = {}
    lines = ["flowchart TD"]
    for c in components:
        lines.append(f'    {_id(c.name, used)}["{_label(c.name)}<br/>{_label(c.path)}"]')
    for c in components:
        for d in c.depends_on:
            if d in used or any(x.name == d for x in components):
                lines.append(f"    {_id(c.name, used)} --> {_id(d, used)}")
    if len(lines) == len(components) + 1 and len(components) > 1:  # no dependencies recorded: show them as one group
        lines.append("    " + " ~~~ ".join(_id(c.name, used) for c in components))
    if not components:
        lines.append('    System["System"] --> Store["Storage"]')
    return "\n".join(lines)


def context_fallback(project: str, personas: list[str], dependencies: list[str]) -> str:
    used: dict[str, str] = {}
    sysid = "System"
    lines = ["flowchart LR", f'    {sysid}["{_label(project or "System")}"]']
    for p in personas[:5] or ["User"]:
        lines.append(f'    {_id(p, used)}(["{_label(p)}"]) --> {sysid}')
    for d in dependencies[:5]:
        lines.append(f'    {sysid} --> {_id("dep " + d, used)}["{_label(d)}"]')
    return "\n".join(lines)


def flow_fallback(steps: list[str]) -> str:
    lines = ["flowchart TD"]
    for i, s in enumerate(steps[:12]):
        lines.append(f'    S{i}["{_label(s)}"]')
        if i:
            lines.append(f"    S{i - 1} --> S{i}")
    if len(steps) < 2:
        lines.append('    S0["Start"] --> S1["Done"]')
    return "\n".join(lines)


def er_fallback(entities: list) -> str:
    lines = ["erDiagram"]
    for e in entities:
        nm = re.sub(r"[^A-Za-z0-9_]", "_", e.name) or "ENTITY"
        lines.append(f"    {nm} {{")
        for f in e.fields[:12]:
            col = re.sub(r"[^A-Za-z0-9_]", "_", f.split(":")[0].strip()) or "field"
            typ = re.sub(r"[^A-Za-z0-9_]", "", f.split(":")[1].split("-")[0].strip().split(" ")[0]) if ":" in f else "string"
            lines.append(f"        {typ or 'string'} {col}")
        lines.append("    }")
    return "\n".join(lines)
