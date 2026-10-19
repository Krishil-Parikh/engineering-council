import { describe, expect, it } from 'vitest';
import { toWorkspaceAgent } from './toWorkspaceAgent';

describe('toWorkspaceAgent', () => {
  it('maps UI-specific agent data into the canonical model', () => {
    expect(toWorkspaceAgent({ id: 'agent-1', name: 'Agent-01', role: 'Developer Agent', status: 'active', avatarColor: '#000' })).toMatchObject({
      id: 'agent-1', name: 'Agent-01', role: 'Developer Agent', status: 'active',
    });
  });
});
