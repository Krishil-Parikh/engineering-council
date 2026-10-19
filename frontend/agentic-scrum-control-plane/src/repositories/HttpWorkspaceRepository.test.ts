import { describe, expect, it, vi } from 'vitest';
import { HttpWorkspaceRepository, mapSnapshotHttpError } from './HttpWorkspaceRepository';

const snapshot = { workspaceId: 'workspace-1', version: 1, phaseId: 'kickoff', agents: [], messages: [], skills: [], artifacts: [], meets: [], sprints: [], edges: [], metrics: { totalMessagesToday: 0, totalPRs: 0, prHistory: [] }, processedEventIds: [] };

function createEventSourceHarness() {
  const listeners = new Map<string, Set<(payload: unknown) => void>>();
  const source = {
    addEventListener: (type: string, listener: (payload: unknown) => void) => {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type)?.add(listener);
    },
    removeEventListener: (type: string, listener: (payload: unknown) => void) => {
      listeners.get(type)?.delete(listener);
    },
    close: vi.fn(),
  };
  return { source: source as unknown as EventSource, listeners };
}

describe('HttpWorkspaceRepository', () => {
  it('loads a snapshot and sends commands through the transport boundary', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(snapshot), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ accepted: true, commandId: 'command-1' }), { status: 200 }));
    const repository = new HttpWorkspaceRepository('https://api.example.test', fetcher);

    await expect(repository.getSnapshot('workspace-1')).resolves.toEqual(snapshot);
    await expect(repository.execute({ type: 'phase.advance', workspaceId: 'workspace-1', phaseId: 'build' })).resolves.toEqual({ accepted: true, commandId: 'command-1' });
    expect(fetcher).toHaveBeenLastCalledWith('https://api.example.test/workspace/workspace-1/commands', expect.objectContaining({ method: 'POST' }));
  });

  it('surfaces failed HTTP responses', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('', { status: 503 }));
    const repository = new HttpWorkspaceRepository('https://api.example.test', fetcher);

    await expect(repository.getSnapshot('workspace-1')).rejects.toThrow('503');
  });

  it('maps permission failures distinctly', () => {
    expect(mapSnapshotHttpError(401).message).toMatch('401');
    expect(mapSnapshotHttpError(403).message).toMatch('403');
    expect(mapSnapshotHttpError(404).message).toMatch('404');
    expect(mapSnapshotHttpError(429).message).toMatch('429');
  });

  it('rejects malformed snapshots without corrupting state', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ nope: true }), { status: 200 }));
    const repository = new HttpWorkspaceRepository('https://api.example.test', fetcher);
    await expect(repository.getSnapshot('workspace-1')).rejects.toThrow('validation');
  });

  it('times out slow snapshot requests', async () => {
    const fetcher = vi.fn((_input: unknown, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      });
    }));
    const repository = new HttpWorkspaceRepository('https://api.example.test', fetcher as typeof fetch, undefined, { timeoutMs: 20 });
    await expect(repository.getSnapshot('workspace-1')).rejects.toThrow('timed out');
  });

  it('dedupes repeat events and ignores malformed payloads', async () => {
    const harness = createEventSourceHarness();
    const repository = new HttpWorkspaceRepository('https://api.example.test', fetch, () => harness.source, { reconnectBaseMs: 100000 });
    const onEvent = vi.fn();
    const onError = vi.fn();
    const unsubscribe = repository.subscribe('workspace-1', onEvent, onError);

    const event = { eventId: 'event-1', workspaceId: 'workspace-1', occurredAt: '', version: 2, type: 'phase.changed', payload: { phaseId: 'build' } };
    const message = (data: string) => ({ data }) as MessageEvent<string>;
    harness.listeners.get('message')?.forEach((listener) => listener(message(JSON.stringify(event))));
    harness.listeners.get('message')?.forEach((listener) => listener(message(JSON.stringify(event))));
    harness.listeners.get('message')?.forEach((listener) => listener(message('not-json')));
    harness.listeners.get('message')?.forEach((listener) => listener(message(JSON.stringify({ nope: true }))));

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledTimes(2);
    unsubscribe();
    expect(harness.source.close).toHaveBeenCalled();
  });
});
