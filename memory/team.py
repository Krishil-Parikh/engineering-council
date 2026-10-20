"""The team's two memories: one project memory that every agent writes to and reads from, and one private memory per agent.

  project memory   shared: the code structure (from the code itself), what each task did, decisions, conventions, APIs, pitfalls, insights. Before new work an agent
                   recalls from it, so it builds on what the others made.
  agent memory     one per agent: its own tasks, habits, mistakes and preferences; recalled only for that agent.

`recall` searches both with the hybrid pipeline (memory.retrieval). `learn` turns what just happened into memories with a model (memory.extract). Structure that can be
read exactly (imports, definitions, which task touched which file) is written without a model."""

from __future__ import annotations

import ast
import asyncio
import re
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from memory import extract as X
from memory.graph import MemoryGraph
from memory.models import MemoryModel
from memory.retrieval import Hit, Query, Retriever

PROJECT = "project"
ME = "me"
SKIP_DIRS = {".git", ".gateway", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build", "out", "output", "coverage", ".next", "target", ".pytest_cache", ".mypy_cache", "site-packages"}  # generated and installed code is not the project


class TeamMemory:
    def __init__(self, root: Optional[Path] = None, model: Optional[MemoryModel] = None) -> None:
        self.root, self.model = (Path(root) if root else None), model
        self.project = MemoryGraph(self.root / "project.sqlite" if self.root else None)
        self._agents: dict[str, MemoryGraph] = {}
        self._retrievers: dict[int, Retriever] = {}
        self._lock = threading.Lock()
        if self.root is not None and (self.root / "agents").is_dir():
            for path in sorted((self.root / "agents").glob("*.sqlite")):
                self._agents[path.stem] = MemoryGraph(path)

    # ------------------------------------------------------------------ the graphs

    def agent(self, name: str) -> MemoryGraph:
        key = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        with self._lock:
            if key not in self._agents:
                self._agents[key] = MemoryGraph(self.root / "agents" / f"{key}.sqlite" if self.root else None)
            return self._agents[key]

    def agents(self) -> list[str]:
        with self._lock:
            return sorted(self._agents)

    def retriever(self, graph: MemoryGraph) -> Retriever:
        with self._lock:
            if id(graph) not in self._retrievers:
                self._retrievers[id(graph)] = Retriever(graph, self.model)
            return self._retrievers[id(graph)]

    def graph_for(self, scope: str) -> MemoryGraph:
        return self.project if scope in (PROJECT, "") else self.agent(scope)

    # ------------------------------------------------------------------ what agents write (the remember tool)

    def remember(self, author: str, scope: str, kind: str, name: str, text: str = "", links: Iterable[tuple[str, str, str]] = (), importance: float = 6.0, tags: Iterable[str] = ()) -> str:
        graph = self.project if scope == PROJECT else self.agent(author)
        node = graph.node(kind, name, text, author, tags, importance)
        graph.link(("agent", author), "wrote", (node.kind, node.name), owner=author)
        for rel, other_kind, other_name in links:
            rk, rn = X.resolve(graph, other_kind, other_name)
            graph.link((node.kind, node.name), rel, (rk, rn), owner=author)
        return f"Remembered in {'the project' if scope == PROJECT else 'your own'} memory: [{node.kind}] {node.name}"

    # ------------------------------------------------------------------ what agents read

    def search(self, scope: str, query: "str | Query", k: int = 10, rerank: bool = False) -> list[Hit]:
        retriever = self.retriever(self.graph_for(scope))
        return retriever.search(retriever.understand(query) if isinstance(query, str) and self.model is not None else query, k=k, rerank=rerank)

    def recall_sync(self, dev: str, query: str, k_project: int = 6, k_agent: int = 4, rerank: bool = False, limit: int = 3200) -> str:
        parts = []
        project_hits = self.search(PROJECT, query, k_project, rerank)
        own_hits = self.search(dev, query, k_agent, rerank)
        if project_hits:
            parts.append("Project memory (what the whole team has built, decided and learned):\n" + self.retriever(self.project).render(project_hits, limit))
        if own_hits:
            parts.append(f"Your own memory ({dev}):\n" + self.retriever(self.agent(dev)).render(own_hits, limit // 2))
        return "\n\n".join(parts)

    async def recall(self, dev: str, query: str, **kw: Any) -> str:
        """What the project and this agent know about a question (empty when nothing matches). Runs in a worker thread: it may call the model."""
        return await asyncio.to_thread(self.recall_sync, dev, query, **{"rerank": self.model is not None, **kw})

    # ------------------------------------------------------------------ what the system notices from the code itself (exact, no model)

    def ingest_codemap(self, root: Path) -> int:
        """Python files become memories with what they define, linked by who imports whom. Returns how many files were read."""
        root = Path(root)
        modules: dict[str, str] = {}
        parsed: dict[str, ast.Module] = {}
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if any(part in SKIP_DIRS for part in Path(rel).parts):
                continue
            try:
                parsed[rel] = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError, OSError):
                continue
            dotted = rel[:-3].replace("/", ".")
            modules[dotted[: -len(".__init__")] if dotted.endswith(".__init__") else dotted] = rel
        for rel, tree in parsed.items():
            defs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not n.name.startswith("_")]
            doc = (ast.get_docstring(tree) or "").split("\n")[0]
            self.project.node("file", rel, " ".join(filter(None, [doc, ("defines " + ", ".join(defs[:14])) if defs else ""])), None, ["code"], 4.0)
            targets: set[str] = set()
            for n in ast.walk(tree):
                names = ([a.name for a in n.names] if isinstance(n, ast.Import) else ([n.module] + [f"{n.module}.{a.name}" for a in n.names]) if isinstance(n, ast.ImportFrom) and n.module else [])
                targets.update(modules[name] for name in names if name in modules and modules[name] != rel)
            for target in sorted(targets):
                self.project.link(("file", rel), "imports", ("file", target))
        return len(parsed)

    def ingest_task(self, dev: str, feature: str, task: str, files: Iterable[str], summary: str = "", ok: bool = True) -> None:
        """A task is done (or failed): what it was, who did it, which files it touched. Goes to the project graph, and to the agent's own."""
        files = list(files)[:40]
        name = f"{feature}: {task}"
        for graph in (self.project, self.agent(dev)):
            graph.node("task", name, ("did not finish. " if not ok else "") + summary[:400], dev, [], 5.0 if ok else 7.0)
            graph.link(("task", name), "belongs_to", ("feature", feature), owner=dev)
            graph.link(("task", name), "done_by" if ok else "struggled_with_by", ("agent", dev), owner=dev)
            for f in files:
                graph.link(("task", name), "touched", ("file", f), owner=dev)

    def ingest_decision(self, title: str, approved: bool, proposer: str, reason: str = "", change: str = "") -> None:
        text = ("approved. " if approved else "rejected. ") + (reason or "")[:300] + (" Change: " + change[:300] if change else "")
        self.project.node("decision", title, text, proposer, ["design"], 8.0 if approved else 6.0)
        self.project.link(("decision", title), "proposed_by", ("agent", proposer), owner=proposer)
        for f in sorted(set(re.findall(r"[\w./-]+\.(?:py|ts|tsx|md|json|toml)", f"{reason} {change}")))[:8]:
            rk, rn = X.resolve(self.project, "file", f)
            self.project.link(("decision", title), "affects", (rk, rn), owner=proposer)

    def ingest_conflict(self, feature: str, files: Iterable[str], resolved: bool, dev: str = "") -> None:
        files = list(files)[:10]
        name = f"merge conflict in {', '.join(files)}" if files else f"merge conflict in {feature}"
        self.project.node("pitfall", name, f"{'resolved' if resolved else 'NOT resolved'} when merging {feature}; branches that touch the same files should be coordinated", dev or None, ["merge"], 7.0)
        self.project.link(("pitfall", name), "hit", ("feature", feature))
        for f in files:
            rk, rn = X.resolve(self.project, "file", f)
            self.project.link(("pitfall", name), "about", (rk, rn))
        if dev:
            self.agent(dev).node("pitfall", name, f"I hit this merging {feature}", dev, ["merge"], 6.0)

    def ingest_feature(self, dev: str, feature: str, title: str, status: str, summary: str = "") -> None:
        self.project.node("feature", feature, f"{title}. {status}. {summary}"[:500], dev, [], 6.0)
        self.project.link(("feature", feature), "owned_by", ("agent", dev), owner=dev)
        self.agent(dev).node("feature", feature, f"{title}. {status}.", dev, [], 5.0)

    # ------------------------------------------------------------------ what a model makes of what happened

    def learn_sync(self, event: X.Event) -> dict[str, int]:
        """Extracts memories from an event and reconciles each with what is known. Returns how many of each operation were done."""
        done: dict[str, int] = {}
        for cand in X.extract(self.model, event):
            graph = self.agent(event.author) if cand.scope == "agent" else self.project
            op = X.apply(graph, self.retriever(graph), self.model, cand, event.author)
            done[op] = done.get(op, 0) + 1
        return done

    async def learn(self, event: X.Event) -> dict[str, int]:
        return await asyncio.to_thread(self.learn_sync, event)

    async def reflect(self, dev: Optional[str] = None) -> int:
        """Writes insights for the project (dev None) or one agent."""
        graph = self.agent(dev) if dev else self.project
        made = await asyncio.to_thread(X.reflect, graph, self.model, dev or "team")
        return len(made)

    # ------------------------------------------------------------------ for people

    def export(self, scope: str = PROJECT, limit: int = 400) -> dict[str, Any]:
        return {"scope": scope, **self.graph_for(scope).export(limit)}

    def overview(self) -> dict[str, Any]:
        return {"project": self.project.stats(), "agents": {name: self.agent(name).stats() for name in self.agents()}}

    def report(self) -> str:
        lines = ["# Team memory", "", f"Project: {self.project.stats()}", ""]
        for kind, heading in (("insight", "Insights"), ("decision", "Decisions"), ("convention", "Conventions"), ("api", "APIs"), ("pitfall", "Pitfalls"), ("how-to", "How-to"), ("note", "Notes")):
            items = sorted((n for n in self.project.nodes() if n.kind == kind), key=lambda n: -(n.importance + n.mentions * 0.2))[:40]
            if items:
                lines += [f"## {heading}", *[f"- **{n.name}**: {n.text}" for n in items], ""]
        for name in self.agents():
            lines += [f"## {name}'s own memory", f"{self.agent(name).stats()}", ""]
        return "\n".join(lines)
