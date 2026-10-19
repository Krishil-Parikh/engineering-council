import type { AppConfig } from '../app/config';
import { createDemoWorkspaceSnapshot } from '../adapters/createDemoWorkspaceSnapshot';
import { HttpWorkspaceRepository } from './HttpWorkspaceRepository';
import { MockWorkspaceRepository } from './MockWorkspaceRepository';
import type { WorkspaceRepository } from './WorkspaceRepository';

/**
 * The single call site that turns configuration into a backend. Views and
 * state never choose a transport; pointing at a real backend is a config
 * change, not a code change.
 */
export function createRepositoryFromConfig(config: AppConfig): WorkspaceRepository {
  if (config.transport === 'mock') {
    return new MockWorkspaceRepository(createDemoWorkspaceSnapshot(config.workspaceId));
  }
  return new HttpWorkspaceRepository(config.apiBaseUrl);
}
