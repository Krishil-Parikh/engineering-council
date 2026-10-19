import type { WorkspaceCommand, CommandResult } from '../domain/commands';
import type { WorkspaceEvent, WorkspaceSnapshot } from '../domain/types';

export interface WorkspaceRepository {
  getSnapshot(workspaceId: string): Promise<WorkspaceSnapshot>;
  execute(command: WorkspaceCommand): Promise<CommandResult>;
  subscribe(
    workspaceId: string,
    onEvent: (event: WorkspaceEvent) => void,
    onError?: (error: Error) => void,
  ): () => void;
}
