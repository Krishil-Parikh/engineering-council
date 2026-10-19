import { describe, expect, it, vi } from 'vitest';
import { WorkspaceStore } from './workspaceStore';

describe('WorkspaceStore', () => {
  it('notifies subscribers only when an event changes the snapshot', () => {
    const store = new WorkspaceStore({ workspaceId: 'workspace-1', version: 1, phaseId: 'kickoff', agents: [], messages: [], skills: [], artifacts: [], meets: [], sprints: [], edges: [], metrics: { totalMessagesToday: 0, totalPRs: 0, prHistory: [] }, processedEventIds: [] });
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    const event = { eventId: 'event-1', workspaceId: 'workspace-1', occurredAt: '', version: 2, type: 'phase.changed' as const, payload: { phaseId: 'brainstorm' as const } };

    store.apply(event);
    store.apply(event);
    expect(listener).toHaveBeenCalledOnce();
    expect(store.getSnapshot().phaseId).toBe('brainstorm');

    unsubscribe();
    store.apply({ ...event, eventId: 'event-2', version: 3, payload: { phaseId: 'prd' } });
    expect(listener).toHaveBeenCalledOnce();
  });
});
