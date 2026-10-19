import { describe, expect, it } from 'vitest';
import { applyWorkspaceEvent } from './reducers';
import type { WorkspaceSnapshot } from './types';

const snapshot: WorkspaceSnapshot = {
  workspaceId: 'workspace-1',
  version: 1,
  phaseId: 'kickoff',
  agents: [{ id: 'agent-1', name: 'Agent-01', role: 'Backend', status: 'idle' }],
  messages: [],
  skills: [], artifacts: [], meets: [], sprints: [], edges: [],
  metrics: { totalMessagesToday: 0, totalPRs: 0, prHistory: [] },
  processedEventIds: [],
};

describe('applyWorkspaceEvent', () => {
  it('applies a new event without mutating the previous snapshot', () => {
    const event = {
      eventId: 'event-1',
      workspaceId: 'workspace-1',
      occurredAt: '2026-09-24T00:00:00Z',
      version: 2,
      type: 'agent.updated' as const,
      payload: { id: 'agent-1', name: 'Agent-01', role: 'Backend', status: 'active' as const },
    };

    const next = applyWorkspaceEvent(snapshot, event);

    expect(next).not.toBe(snapshot);
    expect(next.agents[0].status).toBe('active');
    expect(snapshot.agents[0].status).toBe('idle');
  });

  it('ignores duplicate event IDs', () => {
    const event = {
      eventId: 'event-duplicate',
      workspaceId: 'workspace-1',
      occurredAt: '2026-09-24T00:00:00Z',
      version: 2,
      type: 'phase.changed' as const,
      payload: { phaseId: 'brainstorm' as const },
    };
    const once = applyWorkspaceEvent(snapshot, event);
    const twice = applyWorkspaceEvent(once, event);

    expect(twice).toBe(once);
  });

  it('ignores events from another workspace and stale versions', () => {
    const otherWorkspace = applyWorkspaceEvent(snapshot, {
      eventId: 'other', workspaceId: 'workspace-2', occurredAt: '', version: 2,
      type: 'phase.changed', payload: { phaseId: 'ship' },
    });
    const stale = applyWorkspaceEvent(snapshot, {
      eventId: 'stale', workspaceId: 'workspace-1', occurredAt: '', version: 0,
      type: 'phase.changed', payload: { phaseId: 'ship' },
    });

    expect(otherWorkspace).toBe(snapshot);
    expect(stale).toBe(snapshot);
  });

  it('upserts previously unknown agents, artifacts, meets, skills, sprints, and edges', () => {
    const agentEvent = {
      eventId: 'event-new-agent',
      workspaceId: 'workspace-1',
      occurredAt: '2026-09-24T00:00:00Z',
      version: 2,
      type: 'agent.updated' as const,
      payload: { id: 'agent-9', name: 'Agent-09', role: 'QA', status: 'active' as const },
    };
    const withAgent = applyWorkspaceEvent(snapshot, agentEvent);
    expect(withAgent.agents).toHaveLength(2);
    expect(withAgent.agents[1].id).toBe('agent-9');

    const withArtifact = applyWorkspaceEvent(withAgent, {
      eventId: 'event-new-artifact', workspaceId: 'workspace-1', occurredAt: '', version: 3,
      type: 'artifact.updated',
      payload: { id: 'art-1', title: 'PRD', filename: 'PRD.md', status: 'in_review' as const, currentVersion: 'v1.0', acceptedCount: 1, totalRequired: 2 },
    });
    expect(withArtifact.artifacts).toHaveLength(1);

    const withSkill = applyWorkspaceEvent(withArtifact, {
      eventId: 'event-new-skill', workspaceId: 'workspace-1', occurredAt: '', version: 4,
      type: 'skill.updated',
      payload: { id: 'skill-1', name: 'Backend', claimedCount: 1 },
    });
    expect(withSkill.skills).toHaveLength(1);

    const withSprint = applyWorkspaceEvent(withSkill, {
      eventId: 'event-new-sprint', workspaceId: 'workspace-1', occurredAt: '', version: 5,
      type: 'sprint.updated',
      payload: { id: 'sprint-1', number: '01', title: 'Sprint 01', phase: 'Build', progress: 10, status: 'active' as const },
    });
    expect(withSprint.sprints).toHaveLength(1);

    const withEdge = applyWorkspaceEvent(withSprint, {
      eventId: 'event-new-edge', workspaceId: 'workspace-1', occurredAt: '', version: 6,
      type: 'edge.updated',
      payload: { id: 'edge-1', source: 'agent-1', target: 'agent-9', isActive: true, latencyMs: 5 },
    });
    expect(withEdge.edges).toHaveLength(1);

    const withMeet = applyWorkspaceEvent(withEdge, {
      eventId: 'event-new-meet', workspaceId: 'workspace-1', occurredAt: '', version: 7,
      type: 'meet.updated',
      payload: { id: 'meet-1', title: 'Meet 01', status: 'live' as const, consensusRate: 10, debateIntensity: 5 },
    });
    expect(withMeet.meets).toHaveLength(1);
  });

  it('applies same-version events with new ids without moving the version backwards', () => {
    const first = applyWorkspaceEvent(snapshot, {
      eventId: 'same-version-1', workspaceId: 'workspace-1', occurredAt: '', version: 2,
      type: 'metrics.updated', payload: { totalMessagesToday: 1, totalPRs: 1, prHistory: [] },
    });
    const second = applyWorkspaceEvent(first, {
      eventId: 'same-version-2', workspaceId: 'workspace-1', occurredAt: '', version: 2,
      type: 'metrics.updated', payload: { totalMessagesToday: 2, totalPRs: 2, prHistory: [] },
    });
    expect(second.version).toBe(2);
    expect(second.metrics.totalPRs).toBe(2);
  });

  it('ignores duplicate message ids without recording a second event', () => {
    const message = { id: 'msg-1', meetId: 'meet-1', senderId: 'agent-1', senderName: 'Agent-01', text: 'Hi', timestamp: '10:00:00' };
    const created = applyWorkspaceEvent(snapshot, {
      eventId: 'message-1', workspaceId: 'workspace-1', occurredAt: '', version: 2,
      type: 'message.created', payload: message,
    });
    const duplicate = applyWorkspaceEvent(created, {
      eventId: 'message-2', workspaceId: 'workspace-1', occurredAt: '', version: 3,
      type: 'message.created', payload: message,
    });
    expect(duplicate.messages).toHaveLength(1);
  });
});
