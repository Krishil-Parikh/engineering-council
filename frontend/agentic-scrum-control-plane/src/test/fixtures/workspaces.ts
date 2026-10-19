import type { WorkspaceSnapshot } from '../../domain/types';

function base(workspaceId: string): WorkspaceSnapshot {
  return {
    workspaceId,
    version: 1,
    phaseId: 'kickoff',
    agents: [],
    messages: [],
    skills: [],
    artifacts: [],
    meets: [],
    sprints: [],
    edges: [],
    metrics: { totalMessagesToday: 0, totalPRs: 0, prHistory: [] },
    processedEventIds: [],
  };
}

export function emptyWorkspace(workspaceId = 'workspace-empty'): WorkspaceSnapshot {
  return base(workspaceId);
}

export function activeSprintWorkspace(workspaceId = 'workspace-active'): WorkspaceSnapshot {
  return {
    ...base(workspaceId),
    version: 4,
    phaseId: 'build',
    agents: [
      { id: 'agent-1', name: 'Agent-01', role: 'Backend', status: 'active', activeTask: 'Build API' },
      { id: 'agent-2', name: 'Agent-02', role: 'Frontend', status: 'speaking', activeTask: 'Build UI' },
    ],
    meets: [{ id: 'meet-1', title: 'Meet 01', status: 'live', consensusRate: 50, debateIntensity: 20 }],
    messages: [
      { id: 'msg-1', meetId: 'meet-1', senderId: 'agent-1', senderName: 'Agent-01', text: 'Started', timestamp: '10:00:00' },
    ],
    artifacts: [{ id: 'art-1', title: 'PRD', filename: 'PRD.md', status: 'in_review', currentVersion: 'v1.0', acceptedCount: 1, totalRequired: 2 }],
    sprints: [{ id: 'sprint-1', number: '01', title: 'Sprint 01', phase: 'Build', progress: 40, status: 'active' }],
    edges: [{ id: 'e-1', source: 'agent-1', target: 'agent-2', label: 'Sync', isActive: true, latencyMs: 5 }],
    metrics: { totalMessagesToday: 1, totalPRs: 3, prHistory: [{ time: 'now', prs: 3 }] },
  };
}

export function blockedAgentWorkspace(workspaceId = 'workspace-blocked'): WorkspaceSnapshot {
  const snapshot = activeSprintWorkspace(workspaceId);
  return {
    ...snapshot,
    agents: snapshot.agents.map((agent) => (agent.id === 'agent-1' ? { ...agent, status: 'blocked' as const } : agent)),
  };
}

export function completedSprintWorkspace(workspaceId = 'workspace-completed'): WorkspaceSnapshot {
  const snapshot = activeSprintWorkspace(workspaceId);
  return {
    ...snapshot,
    phaseId: 'ship',
    meets: snapshot.meets.map((meet) => ({ ...meet, status: 'completed' as const, consensusRate: 100 })),
    artifacts: snapshot.artifacts.map((artifact) => ({ ...artifact, status: 'approved' as const, acceptedCount: 2 })),
    sprints: snapshot.sprints.map((sprint) => ({ ...sprint, status: 'completed' as const, progress: 100 })),
  };
}

export function partiallyAcceptedArtifactWorkspace(workspaceId = 'workspace-partial'): WorkspaceSnapshot {
  const snapshot = activeSprintWorkspace(workspaceId);
  return {
    ...snapshot,
    artifacts: [
      { id: 'art-1', title: 'PRD', filename: 'PRD.md', status: 'in_review', currentVersion: 'v0.9', acceptedCount: 1, totalRequired: 6 },
    ],
  };
}
