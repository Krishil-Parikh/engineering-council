import { describe, expect, it } from 'vitest';
import { createInitialWorkspaceSnapshot } from '../adapters/control-plane/toWorkspaceSnapshot';
import { MockWorkspaceRepository } from '../repositories/MockWorkspaceRepository';
import { WorkspaceStore } from './workspaceStore';
import { selectAgent, selectMeetMessages } from '../domain/selectors';

describe('shared workspace integration', () => {
  it('keeps the normalized Control Plane data and live GenUI events in one state model', async () => {
    const initial = createInitialWorkspaceSnapshot('workspace-1');
    const repository = new MockWorkspaceRepository(initial);
    const store = new WorkspaceStore(await repository.getSnapshot('workspace-1'));
    const agent = initial.agents[0];
    const message = initial.messages[0];

    expect(selectAgent(store.getSnapshot(), agent.id)).toMatchObject({ id: agent.id });
    expect(selectMeetMessages(store.getSnapshot(), message.meetId)).toContainEqual(message);

    repository.subscribe('workspace-1', store.apply);
    repository.emit({
      eventId: 'genui-agent-update',
      workspaceId: 'workspace-1',
      occurredAt: '2026-09-24T00:00:00Z',
      version: 2,
      type: 'agent.updated',
      payload: { ...agent, status: 'speaking', activeTask: 'Shared task' },
    });

    expect(selectAgent(store.getSnapshot(), agent.id)).toMatchObject({ status: 'speaking', activeTask: 'Shared task' });
  });
});
