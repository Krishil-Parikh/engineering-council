import { describe, expect, it } from 'vitest';
import { validateWorkspaceCommand } from './commands';

describe('validateWorkspaceCommand', () => {
  it('accepts every canonical command shape', () => {
    const workspaceId = 'workspace-1';
    expect(validateWorkspaceCommand({ type: 'sprint.start', workspaceId, brief: 'Ship it' })).toEqual({ ok: true });
    expect(validateWorkspaceCommand({ type: 'phase.advance', workspaceId, phaseId: 'build' })).toEqual({ ok: true });
    expect(validateWorkspaceCommand({ type: 'agent.task.reassign', workspaceId, agentId: 'agent-1', task: 'Do it' })).toEqual({ ok: true });
    expect(validateWorkspaceCommand({
      type: 'message.create', workspaceId,
      message: { meetId: 'meet-1', senderId: 'agent-1', senderName: 'Agent-01', text: 'Hi', timestamp: '10:00:00' },
    })).toEqual({ ok: true });
    expect(validateWorkspaceCommand({ type: 'sme.directive.submit', workspaceId, meetId: 'meet-1', directive: 'Use Raft' })).toEqual({ ok: true });
    expect(validateWorkspaceCommand({ type: 'prd.accept', workspaceId, artifactId: 'art-1' })).toEqual({ ok: true });
    expect(validateWorkspaceCommand({ type: 'debate.inject', workspaceId, meetId: 'meet-1', text: 'Challenge' })).toEqual({ ok: true });
    expect(validateWorkspaceCommand({ type: 'consensus.force', workspaceId, meetId: 'meet-1' })).toEqual({ ok: true });
  });

  it('rejects unknown types, missing workspace ids, and empty payloads', () => {
    expect(validateWorkspaceCommand(null)).toEqual({ ok: false, error: 'Command must be an object' });
    expect(validateWorkspaceCommand({ type: 'nope', workspaceId: 'workspace-1' }).ok).toBe(false);
    expect(validateWorkspaceCommand({ type: 'sprint.start', workspaceId: '', brief: 'x' }).ok).toBe(false);
    expect(validateWorkspaceCommand({ type: 'sprint.start', workspaceId: 'workspace-1', brief: '  ' }).ok).toBe(false);
    expect(validateWorkspaceCommand({ type: 'agent.task.reassign', workspaceId: 'workspace-1', agentId: 'agent-1', task: '' }).ok).toBe(false);
    expect(validateWorkspaceCommand({ type: 'sme.directive.submit', workspaceId: 'workspace-1', meetId: 'meet-1', directive: '' }).ok).toBe(false);
    expect(validateWorkspaceCommand({ type: 'debate.inject', workspaceId: 'workspace-1', meetId: 'meet-1', text: '' }).ok).toBe(false);
    expect(validateWorkspaceCommand({ type: 'consensus.force', workspaceId: 'workspace-1', meetId: '' }).ok).toBe(false);
    expect(validateWorkspaceCommand({ type: 'prd.accept', workspaceId: 'workspace-1', artifactId: '' }).ok).toBe(false);
  });
});
