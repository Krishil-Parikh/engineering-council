import type { CommandResult, WorkspaceCommand } from '../domain/commands';
import { applyWorkspaceEvent } from '../domain/reducers';
import type { PhaseId, WorkspaceAgent, WorkspaceEvent, WorkspaceMessage, WorkspaceSnapshot } from '../domain/types';
import type { WorkspaceRepository } from '../repositories/WorkspaceRepository';

/** A stand-in for a real backend: it is "live" (so the views drop their demo choreography), records every command, and lets a test push events. */
export class LiveFakeRepository implements WorkspaceRepository {
  readonly live = true;
  readonly commands: WorkspaceCommand[] = [];
  private snapshot: WorkspaceSnapshot;
  private readonly listeners = new Set<(event: WorkspaceEvent) => void>();
  private version: number;

  constructor(snapshot: WorkspaceSnapshot) {
    this.snapshot = structuredClone(snapshot);
    this.version = snapshot.version;
  }

  async getSnapshot() {
    return structuredClone(this.snapshot);
  }

  async execute(command: WorkspaceCommand): Promise<CommandResult> {
    this.commands.push(command);
    return { accepted: true, commandId: `cmd-${this.commands.length}` };
  }

  subscribe(_workspaceId: string, onEvent: (event: WorkspaceEvent) => void) {
    this.listeners.add(onEvent);
    return () => this.listeners.delete(onEvent);
  }

  push<T extends WorkspaceEvent['type']>(type: T, payload: Extract<WorkspaceEvent, { type: T }>['payload']) {
    this.version += 1;
    const event = {
      eventId: `evt-${this.version}`, workspaceId: this.snapshot.workspaceId, occurredAt: new Date().toISOString(), version: this.version, type, payload,
    } as WorkspaceEvent;
    this.snapshot = applyWorkspaceEvent(this.snapshot, event);
    this.listeners.forEach((listener) => listener(event));
  }

  phase(phaseId: PhaseId) {
    this.push('phase.changed', { phaseId });
  }

  message(message: Partial<WorkspaceMessage> & { id: string; text: string }) {
    this.push('message.created', { meetId: 'meet-01', senderId: 'agent-sm', senderName: 'Scrum Master', timestamp: '10:00:00', ...message });
  }

  agent(agent: WorkspaceAgent) {
    this.push('agent.updated', agent);
  }

  metrics(metrics: WorkspaceSnapshot['metrics']) {
    this.push('metrics.updated', metrics);
  }

  commandsOfType(type: WorkspaceCommand['type']) {
    return this.commands.filter((command) => command.type === type);
  }
}

/** What a freshly created workspace looks like from the gateway: never empty (the scrum master and you), at the kickoff phase. */
export function idleLiveWorkspace(workspaceId = 'workspace-live'): WorkspaceSnapshot {
  return {
    workspaceId,
    version: 3,
    phaseId: 'kickoff',
    agents: [
      { id: 'agent-sm', name: 'Scrum Master', role: 'Scrum Master', status: 'idle' },
      { id: 'sme-01', name: 'SME-01', role: 'Business SME (you)', status: 'idle' },
    ],
    messages: [],
    skills: [],
    artifacts: [],
    meets: [],
    sprints: [],
    edges: [],
    metrics: { totalMessagesToday: 0, totalPRs: 0, prHistory: [] },
    processedEventIds: [],
  };
}
