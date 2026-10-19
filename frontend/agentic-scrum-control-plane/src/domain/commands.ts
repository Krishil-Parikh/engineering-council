import type { PhaseId } from './types';

export type WorkspaceCommand =
  | { type: 'sprint.start'; workspaceId: string; brief: string }
  | { type: 'phase.advance'; workspaceId: string; phaseId: PhaseId }
  | { type: 'agent.task.reassign'; workspaceId: string; agentId: string; task: string }
  | { type: 'message.create'; workspaceId: string; message: Omit<import('./types').WorkspaceMessage, 'id'> }
  | { type: 'sme.directive.submit'; workspaceId: string; directive: string; meetId: string }
  | { type: 'prd.accept'; workspaceId: string; artifactId: string }
  | { type: 'debate.inject'; workspaceId: string; meetId: string; text: string }
  | { type: 'consensus.force'; workspaceId: string; meetId: string };

export interface CommandResult {
  accepted: boolean;
  commandId: string;
}

const COMMAND_TYPES: WorkspaceCommand['type'][] = [
  'sprint.start',
  'phase.advance',
  'agent.task.reassign',
  'message.create',
  'sme.directive.submit',
  'prd.accept',
  'debate.inject',
  'consensus.force',
];

export function validateWorkspaceCommand(command: unknown): { ok: true } | { ok: false; error: string } {
  if (typeof command !== 'object' || command === null) return { ok: false, error: 'Command must be an object' };
  const candidate = command as { type?: unknown; workspaceId?: unknown };
  if (typeof candidate.type !== 'string' || !(COMMAND_TYPES as string[]).includes(candidate.type)) {
    return { ok: false, error: `Unknown command type: ${String(candidate.type)}` };
  }
  if (typeof candidate.workspaceId !== 'string' || candidate.workspaceId.length === 0) {
    return { ok: false, error: 'workspaceId is required' };
  }
  const typed = command as WorkspaceCommand;
  switch (typed.type) {
    case 'sprint.start':
      return typed.brief.trim() ? { ok: true } : { ok: false, error: 'brief is required' };
    case 'phase.advance':
      return typed.phaseId ? { ok: true } : { ok: false, error: 'phaseId is required' };
    case 'agent.task.reassign':
      if (!typed.agentId) return { ok: false, error: 'agentId is required' };
      return typed.task.trim() ? { ok: true } : { ok: false, error: 'task is required' };
    case 'message.create':
      if (!typed.message?.text?.trim()) return { ok: false, error: 'message.text is required' };
      if (!typed.message.meetId) return { ok: false, error: 'message.meetId is required' };
      if (!typed.message.senderId) return { ok: false, error: 'message.senderId is required' };
      return { ok: true };
    case 'sme.directive.submit':
      if (!typed.meetId) return { ok: false, error: 'meetId is required' };
      return typed.directive.trim() ? { ok: true } : { ok: false, error: 'directive is required' };
    case 'prd.accept':
      return typed.artifactId ? { ok: true } : { ok: false, error: 'artifactId is required' };
    case 'debate.inject':
      if (!typed.meetId) return { ok: false, error: 'meetId is required' };
      return typed.text.trim() ? { ok: true } : { ok: false, error: 'text is required' };
    case 'consensus.force':
      return typed.meetId ? { ok: true } : { ok: false, error: 'meetId is required' };
  }
}
