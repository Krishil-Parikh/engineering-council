/** What the team remembers, as the gateway reports it: one graph for the project (every agent writes to it) and one private graph per agent. */

export interface MemoryNode {
  id: string;
  kind: string;
  name: string;
  text: string;
  tags: string[];
  owner: string | null;
  importance: number;
  mentions: number;
  created: number;
  updated: number;
  validFrom: number;
  validTo: number | null;
  supersededBy: string | null;
  degree?: number;
}

export interface MemoryEdge {
  source: string;
  relation: string;
  target: string;
  weight: number;
  note: string;
  owner: string | null;
  validTo: number | null;
}

export interface MemoryStats {
  nodes?: number;
  edges?: number;
  replaced?: number;
  [kind: string]: number | undefined;
}

export interface MemoryGraphData {
  /** False until a team exists (before the build starts). */
  available: boolean;
  /** `project`, or an agent's name. */
  scope: string;
  nodes: MemoryNode[];
  edges: MemoryEdge[];
  stats: MemoryStats;
  /** Agents that have a private memory. */
  agents: string[];
  overview: { project?: MemoryStats; agents?: Record<string, MemoryStats> };
}

/** Why a search found something: its rank by words (BM25) and by meaning (dense), whether the question named it, how close it is through the links, recency, importance. */
export interface MemorySignals {
  bm25?: number | null;
  dense?: number | null;
  cosine?: number | null;
  entity?: boolean;
  graph?: number;
  recency?: number;
  importance?: number;
  via?: 'match' | 'link';
  rerank?: number | null;
}

export interface MemoryHit extends MemoryNode {
  score: number;
  signals: MemorySignals;
}

export interface MemoryApi {
  graph(workspaceId: string, scope: string, limit?: number): Promise<MemoryGraphData>;
  search(workspaceId: string, scope: string, query: string, deep?: boolean): Promise<MemoryHit[]>;
}

export const EMPTY_MEMORY: MemoryGraphData = { available: false, scope: 'project', nodes: [], edges: [], stats: {}, agents: [], overview: {} };
