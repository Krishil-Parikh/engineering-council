"""Finding the right memories: a hybrid pipeline, the way current agent-memory systems do it.

  1. understand the question        (optional, with a model) rewrite it into several searches and imagine an answer (HyDE), so a question phrased differently from the
                                    memory still finds it
  2. three retrievers in parallel   BM25 over names, text and tags (exact words, identifiers, paths); dense vectors (same meaning, different words); entity linking
                                    (names of known things that appear in the question)
  3. fusion                         reciprocal rank fusion: ranks, not scores, so the three scales never have to agree
  4. follow the links               Personalized PageRank from the best hits across the graph (HippoRAG): the bridge nodes that connect two hits, and what depends on
                                    them, come up even though they share no word with the question
  5. final score                    fused relevance + graph proximity, with recency and importance (Generative Agents), replaced facts left out
  6. rerank                         (optional, with a model) the best ~30 are put in order by what actually helps the task

Everything but the model calls is plain Python with no dependencies. Each hit carries the signals that put it there, so a person (or a test) can see why."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from memory.graph import MemoryGraph, Node
from memory.models import MemoryModel

WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "are", "was", "will", "not", "you", "your", "but", "all", "can", "how", "what", "why", "does", "when", "have",
        "has", "its", "our", "use", "used", "using", "should", "would", "could", "about", "which", "there", "their", "them", "then", "than", "also", "any", "each"}
RRF_K = 60
RELATION_WEIGHT = {"imports": 1.0, "affects": 1.2, "depends_on": 1.2, "supports": 1.0, "supersedes": 0.4, "touched": 0.8, "about": 1.0, "part_of": 1.0, "belongs_to": 0.9, "done_by": 0.5,
                   "wrote": 0.4, "owned_by": 0.5, "proposed_by": 0.5, "struggled_with_by": 0.7, "hit": 0.8}


def tokens(text: str) -> list[str]:
    """Words, with identifiers and paths also split (`timer_registry.py` -> timer, registry, py, and the whole), lower-cased, stop words dropped."""
    lowered = text.lower()
    out: list[str] = []
    for chunk in re.findall(r"[a-z0-9_./-]+", lowered):
        out.extend(p for p in WORD.findall(chunk) if p not in STOP)
        for segment in chunk.split("/"):  # each path segment is also an identifier: `timer_registry.py` as one token, and without its extension
            parts = [p for p in WORD.findall(segment) if p not in STOP]
            if len(parts) > 1 and len(segment) <= 60:
                out.append("".join(parts))
                if "." in segment:
                    out.append("".join(p for p in WORD.findall(segment.rsplit(".", 1)[0]) if p not in STOP))
    return out


def node_text(n: Node) -> str:
    return f"{n.name} {n.name} {n.text} {' '.join(n.tags)} {n.kind}"  # the name counts double


class BM25:
    def __init__(self, nodes: list[Node], k1: float = 1.4, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = {n.id: tokens(node_text(n)) for n in nodes}
        self.avg = (sum(len(d) for d in self.docs.values()) / len(self.docs)) if self.docs else 0.0
        self.df: dict[str, int] = {}
        for d in self.docs.values():
            for t in set(d):
                self.df[t] = self.df.get(t, 0) + 1
        self.tf = {nid: {t: d.count(t) for t in set(d)} for nid, d in self.docs.items()}

    def search(self, query: str, k: int = 30) -> list[tuple[str, float]]:
        q = list(dict.fromkeys(tokens(query)))
        n = len(self.docs)
        scored: list[tuple[str, float]] = []
        for nid, tf in self.tf.items():
            length = len(self.docs[nid]) or 1
            score = 0.0
            for t in q:
                f = tf.get(t)
                if not f:
                    continue
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                score += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / (self.avg or 1)))
            if score > 0:
                scored.append((nid, score))
        return sorted(scored, key=lambda t: -t[1])[:k]


def cosine(a: list[float], b: list[float]) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / math.sqrt(na * nb) if na and nb else 0.0


def rrf(rankings: list[list[str]], weights: Optional[list[float]] = None, k: int = RRF_K) -> dict[str, float]:
    """Reciprocal rank fusion: each list gives 1/(k+rank) to its items; the sum puts what several lists agree on first."""
    fused: dict[str, float] = {}
    for i, ranking in enumerate(rankings):
        w = weights[i] if weights else 1.0
        for rank, nid in enumerate(ranking, 1):
            fused[nid] = fused.get(nid, 0.0) + w / (k + rank)
    return fused


def personalized_pagerank(graph: MemoryGraph, seeds: dict[str, float], alpha: float = 0.5, iterations: int = 20, cache: Optional[dict] = None) -> dict[str, float]:
    """Random walks that restart at the seeds: what is close to them in the graph (by many short paths) scores high. Edges count in both directions, by relation."""
    total = sum(seeds.values())
    if not seeds or total <= 0:
        return {}
    if cache is not None and cache.get("version") == graph.version:
        adjacency = cache["adjacency"]
    else:
        adjacency = {}
        for e in graph.edges():
            w = RELATION_WEIGHT.get(e.rel, 0.8) * e.weight
            adjacency.setdefault(e.src, []).append((e.dst, w))
            adjacency.setdefault(e.dst, []).append((e.src, w))
        if cache is not None:
            cache.update(version=graph.version, adjacency=adjacency)
    restart = {nid: s / total for nid, s in seeds.items()}
    rank = dict(restart)
    for _ in range(iterations):
        nxt = {nid: alpha * p for nid, p in restart.items()}
        for nid, mass in rank.items():
            out = adjacency.get(nid)
            if not out:
                nxt[nid] = nxt.get(nid, 0.0) + (1 - alpha) * mass  # a dead end keeps its mass
                continue
            denominator = sum(w for _, w in out)
            for other, w in out:
                nxt[other] = nxt.get(other, 0.0) + (1 - alpha) * mass * w / denominator
        rank = nxt
    return rank


@dataclass
class Hit:
    node: Node
    score: float
    signals: dict[str, Any] = field(default_factory=dict)  # why it is here: bm25 / dense / entity ranks, graph proximity, recency, importance, rerank

    def public(self) -> dict[str, Any]:
        return {**self.node.public(), "score": round(self.score, 4), "signals": self.signals}


@dataclass
class Query:
    text: str
    variants: list[str] = field(default_factory=list)
    hypothetical: str = ""  # an imagined memory that would answer it (HyDE)


class Retriever:
    def __init__(self, graph: MemoryGraph, model: Optional[MemoryModel] = None, half_life_hours: float = 72.0) -> None:
        self.graph, self.model, self.half_life = graph, model, half_life_hours * 3600
        self._bm25: Optional[tuple[int, BM25]] = None
        self._adjacency: dict = {}
        self._vectors: Optional[tuple[int, dict[str, list[float]]]] = None

    # ------------------------------------------------------------------ indexes

    def bm25(self) -> BM25:
        if self._bm25 is None or self._bm25[0] != self.graph.version:
            self._bm25 = (self.graph.version, BM25(self.graph.nodes()))
        return self._bm25[1]

    def ensure_vectors(self) -> int:
        """Embeds the memories that have no vector yet (in batches). Returns how many were added."""
        if self.model is None:
            return 0
        missing = self.graph.missing_vectors(self.model.embed_model)
        if not missing:
            return 0
        try:
            vectors = self.model.embed([node_text(n) for n in missing])
        except Exception:  # noqa: BLE001 - no vectors this time: retrieval goes on by words and links
            return 0
        for node, vector in zip(missing, vectors):
            self.graph.set_vector(node.id, self.model.embed_model, vector)
        self._vectors = None
        return len(missing)

    def vectors(self) -> dict[str, list[float]]:
        if self.model is None:
            return {}
        if self._vectors is None or self._vectors[0] != self.graph.version:
            self._vectors = (self.graph.version, self.graph.vectors(self.model.embed_model))
        return self._vectors[1]

    # ------------------------------------------------------------------ understanding the question (with a model)

    def understand(self, text: str) -> Query:
        if self.model is None:
            return Query(text)
        try:
            reply = self.model.generate_json(
                "A software agent is looking in its team's memory (notes, decisions, conventions, pitfalls, files and how they connect) for help with this:\n"
                f"{text}\n\nReturn JSON: {{\"searches\": [up to 3 short search phrasings that use different words for the same need], "
                "\"hypothetical\": \"one or two sentences, written as the memory that would answer it\"}")
            variants = [str(v) for v in (reply.get("searches") or [])][:3] if isinstance(reply, dict) else []
            return Query(text, variants, str(reply.get("hypothetical", "")) if isinstance(reply, dict) else "")
        except Exception:  # noqa: BLE001
            return Query(text)

    # ------------------------------------------------------------------ the search

    def search(self, query: "str | Query", k: int = 8, kinds: Optional[Iterable[str]] = None, rerank: bool = False, now: Optional[float] = None) -> list[Hit]:
        q = query if isinstance(query, Query) else Query(query)
        now = now or time.time()
        nodes = {n.id: n for n in self.graph.nodes()}
        if not nodes:
            return []
        texts = [q.text, *q.variants]

        # lexical
        bm25 = self.bm25()
        lexical_scores: dict[str, float] = {}
        for t in texts:
            for nid, s in bm25.search(t, 30):
                lexical_scores[nid] = max(lexical_scores.get(nid, 0.0), s)
        lexical = sorted(lexical_scores, key=lambda n: -lexical_scores[n])[:30]

        # dense
        dense: list[str] = []
        dense_scores: dict[str, float] = {}
        if self.model is not None:
            self.ensure_vectors()
            vectors = self.vectors()
            if vectors:
                try:
                    wanted = [t for t in [q.text, q.hypothetical, *q.variants] if t]
                    query_vectors = self.model.embed(wanted, query=True)
                    for qv in query_vectors:
                        for nid, vec in vectors.items():
                            if nid in nodes:
                                dense_scores[nid] = max(dense_scores.get(nid, -1.0), cosine(qv, vec))
                    dense = sorted(dense_scores, key=lambda n: -dense_scores[n])[:30]
                except Exception:  # noqa: BLE001
                    dense = []

        # entity linking: things the question names
        low = " ".join(texts).lower()
        entity = [nid for nid, n in nodes.items() if len(n.name) >= 4 and n.name.lower() in low and n.kind in ("file", "module", "feature", "decision", "agent", "api")]

        rankings = [r for r in (lexical, dense, entity) if r]
        if not rankings:
            return []
        fused = rrf(rankings, [1.0, 1.2, 1.0][: len(rankings)] if len(rankings) == 3 else None)
        top = sorted(fused, key=lambda n: -fused[n])[:12]

        # the graph: walks that restart at the best hits
        proximity = personalized_pagerank(self.graph, {nid: fused[nid] for nid in top}, cache=self._adjacency)
        max_fused = max(fused.values()) or 1.0
        max_prox = max(proximity.values()) if proximity else 1.0

        wanted_kinds = set(kinds) if kinds else None
        candidates: dict[str, Hit] = {}
        for nid in set(fused) | set(nid for nid, p in proximity.items() if p >= 0.04 * max_prox):
            n = nodes.get(nid)
            if n is None or (wanted_kinds and n.kind not in wanted_kinds):
                continue
            relevance = fused.get(nid, 0.0) / max_fused
            graph_signal = (proximity.get(nid, 0.0) / max_prox) if max_prox else 0.0
            age = max(0.0, now - n.updated)
            recency = 0.5 ** (age / self.half_life)
            importance = n.importance / 10
            score = 0.55 * relevance + 0.25 * graph_signal + 0.10 * recency + 0.10 * importance
            candidates[nid] = Hit(n, score, {
                "bm25": (lexical.index(nid) + 1) if nid in lexical else None, "dense": (dense.index(nid) + 1) if nid in dense else None,
                "cosine": round(dense_scores[nid], 3) if nid in dense_scores else None, "entity": nid in entity,
                "graph": round(graph_signal, 3), "recency": round(recency, 3), "importance": n.importance,
                "via": "match" if nid in fused else "link",
            })
        hits = sorted(candidates.values(), key=lambda h: -h.score)
        if rerank and self.model is not None and len(hits) > 3:
            hits = self._rerank(q.text, hits[:30]) + hits[30:]
        return hits[:k]

    def _rerank(self, text: str, hits: list[Hit]) -> list[Hit]:
        """The model puts the candidates in order of how much they help with the actual task; its order and the pipeline's score are blended, never trusted alone."""
        listing = "\n".join(f"{i}. [{h.node.kind}] {h.node.name}: {h.node.text[:240]}" for i, h in enumerate(hits))
        try:
            reply = self.model.generate_json(  # type: ignore[union-attr]
                f"A software agent needs team memory for this:\n{text}\n\nCandidates:\n{listing}\n\n"
                "Return JSON {\"order\": [candidate numbers, most useful first, only the ones that really help]}.")
            order = [int(i) for i in (reply.get("order") if isinstance(reply, dict) else []) if 0 <= int(i) < len(hits)]
        except Exception:  # noqa: BLE001
            return hits
        if not order:
            return hits
        rank = {i: r for r, i in enumerate(dict.fromkeys(order))}
        for i, h in enumerate(hits):
            h.signals["rerank"] = (rank[i] + 1) if i in rank else None
            h.score = 0.5 * h.score + 0.5 * (1.0 - rank[i] / max(1, len(rank))) if i in rank else 0.5 * h.score * 0.6
        return sorted(hits, key=lambda h: -h.score)

    # ------------------------------------------------------------------ for prompts

    def render(self, hits: list[Hit], limit: int = 3200) -> str:
        out: list[str] = []
        size = 0
        for h in hits:
            n = h.node
            links = [f"{'->' if out_ else '<-'} {rel} {other.name}" for rel, other, out_, _w in self.graph.neighbors(n.id)[:6]]
            when = time.strftime("%H:%M", time.localtime(n.updated))
            line = f"- [{n.kind}] {n.name}" + (f": {n.text}" if n.text else "") + (f"  ({'; '.join(links)})" if links else "") + (f"  — {n.owner}, {when}" if n.owner else "")
            if size + len(line) > limit:
                break
            out.append(line)
            size += len(line)
        return "\n".join(out)
