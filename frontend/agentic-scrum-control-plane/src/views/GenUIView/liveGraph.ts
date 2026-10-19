import type { Edge, Node } from '@xyflow/react';
import type { Agent } from '../../types';
import type { WorkspaceEdge } from '../../domain/types';

const SCRUM_MASTER_NODE = 'scrum-master';
const COLUMN = 250;
const ROW = 190;
const PER_ROW = 4;

function isDeveloper(agent: Agent): boolean {
  return agent.id.startsWith('agent-') && agent.id !== 'agent-sm';
}

/** The build graph for the team that actually exists: the scrum master on top, each developer below, and the delegations between them. */
export function buildLiveGraph(agents: Agent[], edges: WorkspaceEdge[]): { nodes: Node[]; edges: Edge[] } {
  const developers = agents.filter(isDeveloper);
  const width = Math.min(PER_ROW, Math.max(developers.length, 1)) * COLUMN;
  const nodes: Node[] = [
    { id: SCRUM_MASTER_NODE, type: 'scrumMaster', position: { x: Math.max(0, width / 2 - 110), y: 30 }, data: { label: 'Scrum Master' } },
    ...developers.map((agent, index): Node => ({
      id: agent.id,
      type: 'agent',
      position: { x: (index % PER_ROW) * COLUMN + 20, y: 160 + Math.floor(index / PER_ROW) * ROW },
      data: {
        name: agent.name,
        skill: agent.claimedSkill,
        status: agent.status,
        task: agent.currentTask ?? 'Waiting for work',
        branch: agent.activeBranch ?? 'main',
        coverage: '',
      },
    })),
  ];
  const known = new Set(nodes.map((node) => node.id));
  const toNode = (id: string) => (id === 'agent-sm' ? SCRUM_MASTER_NODE : id);
  const links: Edge[] = edges
    .map((edge) => ({ edge, source: toNode(edge.source), target: toNode(edge.target) }))
    .filter(({ source, target }) => known.has(source) && known.has(target) && source !== target)
    .map(({ edge, source, target }): Edge => ({
      id: edge.id,
      source,
      target,
      animated: edge.isActive,
      label: edge.isActive ? edge.label : undefined,
      style: edge.isActive ? { stroke: '#161616', strokeWidth: 1.5 } : { stroke: '#8E8E8E', strokeDasharray: '4 4' },
    }));
  return { nodes, edges: links };
}
