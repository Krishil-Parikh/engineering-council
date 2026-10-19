import type { WorkspaceCommand, CommandResult } from '../domain/commands';
import { validateWorkspaceCommand } from '../domain/commands';
import type { WorkspaceEvent, WorkspaceSnapshot } from '../domain/types';
import type { WorkspaceRepository } from './WorkspaceRepository';
import { applyWorkspaceEvent } from '../domain/reducers';

export class MockWorkspaceRepository implements WorkspaceRepository {
  private readonly listeners = new Set<(event: WorkspaceEvent) => void>();
  private snapshot: WorkspaceSnapshot;
  private readonly initial: WorkspaceSnapshot;

  constructor(snapshot: WorkspaceSnapshot) {
    this.snapshot = structuredClone(snapshot);
    this.initial = structuredClone(snapshot);
  }

  async getSnapshot(workspaceId: string) {
    if (workspaceId !== this.snapshot.workspaceId) {
      throw new Error(`Unknown workspace: ${workspaceId}`);
    }
    return structuredClone(this.snapshot);
  }

  /** Deterministic test control: restore the seed snapshot. */
  reset() {
    this.snapshot = structuredClone(this.initial);
  }

  /** Deterministic test control: replace the seed snapshot. */
  seed(snapshot: WorkspaceSnapshot) {
    this.snapshot = structuredClone(snapshot);
  }

  async execute(command: WorkspaceCommand): Promise<CommandResult> {
    const validation = validateWorkspaceCommand(command);
    if (!validation.ok) throw new Error(`Invalid command: ${validation.error}`);
    if (command.workspaceId !== this.snapshot.workspaceId) {
      throw new Error(`Unknown workspace: ${command.workspaceId}`);
    }
    const commandId = `${command.type}-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
    const version = this.snapshot.version + 1;
    const base = {
      eventId: commandId,
      workspaceId: command.workspaceId,
      occurredAt: new Date().toISOString(),
      version,
    };

    if (command.type === 'phase.advance') {
      this.emit({ ...base, type: 'phase.changed', payload: { phaseId: command.phaseId } });
      if (command.phaseId === 'ship') {
        const metrics = this.snapshot.metrics;
        const prHistory = [...metrics.prHistory];
        const last = prHistory[prHistory.length - 1];
        if (last) prHistory[prHistory.length - 1] = { ...last, prs: last.prs + 1 };
        this.emit({
          ...base,
          eventId: `${commandId}-metrics`,
          version: version + 1,
          type: 'metrics.updated',
          payload: { ...metrics, totalPRs: metrics.totalPRs + 1, prHistory },
        });
      }
    } else if (command.type === 'agent.task.reassign') {
      const agent = this.snapshot.agents.find((item) => item.id === command.agentId);
      if (!agent) throw new Error(`Unknown agent: ${command.agentId}`);
      this.emit({ ...base, type: 'agent.updated', payload: { ...agent, activeTask: command.task } });
    } else if (command.type === 'message.create') {
      this.emit({ ...base, type: 'message.created', payload: { id: `message-${commandId}`, ...command.message } });
    } else if (command.type === 'sprint.start') {
      this.emit({ ...base, type: 'phase.changed', payload: { phaseId: 'brainstorm' } });
    } else if (command.type === 'sme.directive.submit') {
      this.emit({
        ...base,
        type: 'message.created',
        payload: {
          id: `message-${commandId}-sme`,
          meetId: command.meetId,
          senderId: 'sme-01',
          senderName: 'SME-01',
          text: `SME DIRECTIVE: "${command.directive}"`,
          timestamp: new Date().toISOString().slice(11, 19),
        },
      });
    } else if (command.type === 'prd.accept') {
      const artifact = this.snapshot.artifacts.find((item) => item.id === command.artifactId);
      if (!artifact) throw new Error(`Unknown artifact: ${command.artifactId}`);
      this.emit({
        ...base,
        type: 'artifact.updated',
        payload: { ...artifact, status: 'approved', acceptedCount: artifact.totalRequired },
      });
    } else if (command.type === 'debate.inject') {
      this.emit({
        ...base,
        type: 'message.created',
        payload: {
          id: `message-${commandId}-debate`,
          meetId: command.meetId,
          senderId: 'agent-06',
          senderName: 'Agent-06',
          text: command.text,
          timestamp: new Date().toISOString().slice(11, 19),
        },
      });
      const meet = this.snapshot.meets.find((item) => item.id === command.meetId);
      if (meet) {
        this.emit({
          ...base,
          eventId: `${commandId}-meet`,
          version: version + 1,
          type: 'meet.updated',
          payload: { ...meet, debateIntensity: Math.min(100, meet.debateIntensity + 15) },
        });
      }
    } else if (command.type === 'consensus.force') {
      const meet = this.snapshot.meets.find((item) => item.id === command.meetId);
      if (!meet) throw new Error(`Unknown meet: ${command.meetId}`);
      this.emit({
        ...base,
        type: 'meet.updated',
        payload: { ...meet, consensusRate: 100, debateIntensity: 20 },
      });
      for (const artifact of this.snapshot.artifacts) {
        this.emit({
          ...base,
          eventId: `${commandId}-artifact-${artifact.id}`,
          version: version + 1,
          type: 'artifact.updated',
          payload: { ...artifact, status: 'approved', acceptedCount: artifact.totalRequired },
        });
      }
    }

    return { accepted: true, commandId };
  }

  subscribe(workspaceId: string, onEvent: (event: WorkspaceEvent) => void, onError?: (error: Error) => void) {
    if (workspaceId !== this.snapshot.workspaceId) {
      onError?.(new Error(`Unknown workspace: ${workspaceId}`));
      return () => undefined;
    }
    this.listeners.add(onEvent);
    return () => this.listeners.delete(onEvent);
  }

  emit(event: WorkspaceEvent) {
    this.snapshot = applyWorkspaceEvent(this.snapshot, event);
    this.listeners.forEach((listener) => listener(event));
  }
}
