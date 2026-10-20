import type { WorkspaceCommand, CommandResult } from '../domain/commands';
import type { WorkspaceEvent, WorkspaceSnapshot } from '../domain/types';
import type { MemoryApi } from '../domain/memory';
import type { StandupApi } from '../views/standup/models/standup';

export interface WorkspaceRepository {
  /** True for a repository backed by a real backend. Views use it to drop demo choreography (timers, canned text) that only makes sense for the mock. */
  readonly live?: boolean;
  /** The team's memory (project and per agent). Only a real backend has one. */
  readonly memory?: MemoryApi;
  /** The formal Scrum meetings (live and replayable). Both the real backend and the demo provide it. */
  readonly standup?: StandupApi;
  getSnapshot(workspaceId: string): Promise<WorkspaceSnapshot>;
  execute(command: WorkspaceCommand): Promise<CommandResult>;
  subscribe(
    workspaceId: string,
    onEvent: (event: WorkspaceEvent) => void,
    onError?: (error: Error) => void,
  ): () => void;
}
