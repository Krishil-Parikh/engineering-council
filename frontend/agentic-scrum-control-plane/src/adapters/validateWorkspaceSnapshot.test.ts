import { describe, expect, it } from 'vitest';
import { assertWorkspaceSnapshot, isWorkspaceSnapshot } from './validateWorkspaceSnapshot';
import { activeSprintWorkspace } from '../test/fixtures/workspaces';

describe('validateWorkspaceSnapshot', () => {
  it('accepts canonical snapshots and rejects malformed payloads', () => {
    expect(isWorkspaceSnapshot(activeSprintWorkspace('workspace-1'))).toBe(true);
    expect(isWorkspaceSnapshot(null)).toBe(false);
    expect(isWorkspaceSnapshot({ nope: true })).toBe(false);
    expect(isWorkspaceSnapshot({ ...activeSprintWorkspace('workspace-1'), agents: 'nope' })).toBe(false);
    expect(() => assertWorkspaceSnapshot({ nope: true })).toThrow('validation');
  });
});
