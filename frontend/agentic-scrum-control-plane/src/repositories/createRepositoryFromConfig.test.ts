import { describe, expect, it } from 'vitest';
import { createRepositoryFromConfig } from './createRepositoryFromConfig';
import { HttpWorkspaceRepository } from './HttpWorkspaceRepository';
import { MockWorkspaceRepository } from './MockWorkspaceRepository';
import type { AppConfig } from '../app/config';

const base: AppConfig = {
  apiBaseUrl: 'https://api.example.test',
  workspaceId: 'workspace-1',
  transport: 'mock',
  enableSimulation: false,
};

describe('createRepositoryFromConfig', () => {
  it('defaults to the mock repository with seeded demo state', async () => {
    const repository = createRepositoryFromConfig(base);
    expect(repository).toBeInstanceOf(MockWorkspaceRepository);
    const snapshot = await repository.getSnapshot('workspace-1');
    expect(snapshot.workspaceId).toBe('workspace-1');
    expect(snapshot.agents.length).toBeGreaterThan(0);
  });

  it('selects the HTTP repository for http transports', () => {
    expect(createRepositoryFromConfig({ ...base, transport: 'http-sse' })).toBeInstanceOf(HttpWorkspaceRepository);
    expect(createRepositoryFromConfig({ ...base, transport: 'http-websocket' })).toBeInstanceOf(HttpWorkspaceRepository);
  });
});
