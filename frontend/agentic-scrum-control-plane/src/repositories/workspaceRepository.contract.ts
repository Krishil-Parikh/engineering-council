import { describe, expect, it, vi } from 'vitest';
import type { WorkspaceRepository } from './WorkspaceRepository';
import type { WorkspaceSnapshot } from '../domain/types';
import { activeSprintWorkspace } from '../test/fixtures/workspaces';

export function runWorkspaceRepositoryContractSuite(
  name: string,
  createRepository: (snapshot: WorkspaceSnapshot) => WorkspaceRepository,
) {
  describe(`${name} contract`, () => {
    it('loads an isolated snapshot', async () => {
      const repository = createRepository(activeSprintWorkspace('workspace-contract'));
      const first = await repository.getSnapshot('workspace-contract');
      first.phaseId = 'ship';
      expect((await repository.getSnapshot('workspace-contract')).phaseId).not.toBe('ship');
    });

    it('rejects unknown workspaces', async () => {
      const repository = createRepository(activeSprintWorkspace('workspace-contract'));
      await expect(repository.getSnapshot('workspace-missing')).rejects.toThrow();
    });

    it('surfaces command validation errors consistently', async () => {
      const repository = createRepository(activeSprintWorkspace('workspace-contract'));
      await expect(repository.execute({
        type: 'agent.task.reassign',
        workspaceId: 'workspace-contract',
        agentId: '',
        task: '',
      })).rejects.toThrow();
    });

    it('supports subscription cleanup', async () => {
      const repository = createRepository(activeSprintWorkspace('workspace-contract'));
      const listener = vi.fn();
      const unsubscribe = repository.subscribe('workspace-contract', listener);
      unsubscribe();
      expect(listener).not.toHaveBeenCalled();
    });
  });
}
