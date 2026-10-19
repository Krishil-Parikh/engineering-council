import { describe, expect, it, vi } from 'vitest';
import { MockWorkspaceRepository } from './MockWorkspaceRepository';
import type { WorkspaceSnapshot } from '../domain/types';

const snapshot: WorkspaceSnapshot = {
  workspaceId: 'workspace-1', version: 1, phaseId: 'kickoff', agents: [], messages: [], skills: [], artifacts: [], meets: [], sprints: [], edges: [], metrics: { totalMessagesToday: 0, totalPRs: 0, prHistory: [] }, processedEventIds: [],
};

describe('MockWorkspaceRepository', () => {
  it('returns an isolated snapshot and supports subscription cleanup', async () => {
    const repository = new MockWorkspaceRepository(snapshot);
    const first = await repository.getSnapshot('workspace-1');
    first.phaseId = 'ship';
    expect((await repository.getSnapshot('workspace-1')).phaseId).toBe('kickoff');

    const listener = vi.fn();
    const unsubscribe = repository.subscribe('workspace-1', listener);
    repository.emit({ eventId: 'event-1', workspaceId: 'workspace-1', occurredAt: '', version: 2, type: 'phase.changed', payload: { phaseId: 'build' } });
    expect(listener).toHaveBeenCalledOnce();
    unsubscribe();
    repository.emit({ eventId: 'event-2', workspaceId: 'workspace-1', occurredAt: '', version: 3, type: 'phase.changed', payload: { phaseId: 'ship' } });
    expect(listener).toHaveBeenCalledOnce();
  });

  it('turns commands into canonical events', async () => {
    const repository = new MockWorkspaceRepository({
      ...snapshot,
      agents: [{ id: 'agent-1', name: 'Agent-01', role: 'Backend', status: 'idle' }],
    });
    const events: unknown[] = [];
    repository.subscribe('workspace-1', (event) => events.push(event));

    await repository.execute({ type: 'phase.advance', workspaceId: 'workspace-1', phaseId: 'build' });
    await repository.execute({ type: 'agent.task.reassign', workspaceId: 'workspace-1', agentId: 'agent-1', task: 'New task' });
    await repository.execute({ type: 'message.create', workspaceId: 'workspace-1', message: {
      meetId: 'meet-1', senderId: 'agent-1', senderName: 'Agent-01', text: 'Ready', timestamp: '12:00:00',
    } });

    expect(events).toHaveLength(3);
    expect((await repository.getSnapshot('workspace-1')).agents[0].activeTask).toBe('New task');
    expect((await repository.getSnapshot('workspace-1')).messages).toHaveLength(1);
  });

  it('handles sme directives, debates, consensus, and prd acceptance', async () => {
    const repository = new MockWorkspaceRepository({
      ...snapshot,
      meets: [{ id: 'meet-1', title: 'Meet 01', status: 'live', consensusRate: 40, debateIntensity: 30 }],
      artifacts: [{ id: 'art-1', title: 'PRD', filename: 'PRD.md', status: 'in_review', currentVersion: 'v1.0', acceptedCount: 1, totalRequired: 2 }],
    });

    await repository.execute({ type: 'debate.inject', workspaceId: 'workspace-1', meetId: 'meet-1', text: 'Challenge!' });
    let current = await repository.getSnapshot('workspace-1');
    expect(current.messages).toHaveLength(1);
    expect(current.meets[0].debateIntensity).toBe(45);

    await repository.execute({ type: 'sme.directive.submit', workspaceId: 'workspace-1', meetId: 'meet-1', directive: 'Use Raft' });
    current = await repository.getSnapshot('workspace-1');
    expect(current.messages.some((message) => message.senderId === 'sme-01')).toBe(true);

    await repository.execute({ type: 'consensus.force', workspaceId: 'workspace-1', meetId: 'meet-1' });
    current = await repository.getSnapshot('workspace-1');
    expect(current.meets[0].consensusRate).toBe(100);
    expect(current.artifacts[0].status).toBe('approved');

    await repository.execute({ type: 'prd.accept', workspaceId: 'workspace-1', artifactId: 'art-1' });
    current = await repository.getSnapshot('workspace-1');
    expect(current.artifacts[0].acceptedCount).toBe(2);
  });

  it('rejects invalid commands and unknown entities', async () => {
    const repository = new MockWorkspaceRepository(snapshot);
    await expect(repository.execute({ type: 'sprint.start', workspaceId: 'workspace-1', brief: '  ' })).rejects.toThrow('brief');
    await expect(repository.execute({ type: 'agent.task.reassign', workspaceId: 'workspace-1', agentId: 'missing', task: 'x' })).rejects.toThrow('Unknown agent');
    await expect(repository.execute({ type: 'prd.accept', workspaceId: 'workspace-1', artifactId: 'missing' })).rejects.toThrow('Unknown artifact');
  });

  it('bumps PR metrics when shipping and supports reset for deterministic tests', async () => {
    const repository = new MockWorkspaceRepository({
      ...snapshot,
      metrics: { totalMessagesToday: 0, totalPRs: 10, prHistory: [{ time: 'now', prs: 2 }] },
    });
    await repository.execute({ type: 'phase.advance', workspaceId: 'workspace-1', phaseId: 'ship' });
    const shipped = await repository.getSnapshot('workspace-1');
    expect(shipped.metrics.totalPRs).toBe(11);
    expect(shipped.metrics.prHistory[0].prs).toBe(3);

    repository.reset();
    expect((await repository.getSnapshot('workspace-1')).metrics.totalPRs).toBe(10);
  });
});
