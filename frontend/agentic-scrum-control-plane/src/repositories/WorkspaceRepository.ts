import type { WorkspaceCommand, CommandResult } from '../domain/commands';
import type { WorkspaceEvent, WorkspaceSnapshot } from '../domain/types';

export interface WorkspaceRepository {
  /** True for a repository backed by a real backend. Views use it to drop demo choreography (timers, canned text) that only makes sense for the mock. */
  readonly live?: boolean;
  getSnapshot(workspaceId: string): Promise<WorkspaceSnapshot>;
  execute(command: WorkspaceCommand): Promise<CommandResult>;
  subscribe(
    workspaceId: string,
    onEvent: (event: WorkspaceEvent) => void,
    onError?: (error: Error) => void,
  ): () => void;
}
