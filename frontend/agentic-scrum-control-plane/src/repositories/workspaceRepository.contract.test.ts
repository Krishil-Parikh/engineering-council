import { vi } from 'vitest';
import { MockWorkspaceRepository } from './MockWorkspaceRepository';
import { HttpWorkspaceRepository } from './HttpWorkspaceRepository';
import { runWorkspaceRepositoryContractSuite } from './workspaceRepository.contract';

runWorkspaceRepositoryContractSuite('MockWorkspaceRepository', (snapshot) => new MockWorkspaceRepository(snapshot));

runWorkspaceRepositoryContractSuite('HttpWorkspaceRepository', (snapshot) => {
  const fetcher = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === 'POST') {
      return new Response(JSON.stringify({ accepted: true, commandId: 'command-1' }), { status: 200 });
    }
    if (url.includes('workspace-missing')) {
      return new Response('', { status: 404 });
    }
    return new Response(JSON.stringify(snapshot), { status: 200 });
  });
  const eventSourceFactory = () => {
    const listeners = new Map<string, Set<EventListener>>();
    return {
      addEventListener: (type: string, listener: EventListener) => {
        if (!listeners.has(type)) listeners.set(type, new Set());
        listeners.get(type)?.add(listener);
      },
      removeEventListener: (type: string, listener: EventListener) => {
        listeners.get(type)?.delete(listener);
      },
      close: () => undefined,
    } as unknown as EventSource;
  };
  return new HttpWorkspaceRepository('https://api.example.test', fetcher as typeof fetch, eventSourceFactory);
});
