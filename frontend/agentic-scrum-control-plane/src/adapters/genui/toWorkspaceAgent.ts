import type { Agent as GenUIAgent } from '../../types';
import type { WorkspaceAgent } from '../../domain/types';

export function toWorkspaceAgent(agent: GenUIAgent): WorkspaceAgent {
  return {
    id: agent.id,
    name: agent.name,
    role: agent.role,
    status: agent.status === 'complete' ? 'complete' : agent.status === 'active' ? 'active' : agent.status === 'blocked' ? 'blocked' : 'idle',
    activeTask: agent.currentTask,
  };
}
