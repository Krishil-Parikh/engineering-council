import { describe, expect, it } from 'vitest';
import { createInitialWorkspaceSnapshot } from './toWorkspaceSnapshot';

describe('createInitialWorkspaceSnapshot', () => {
  it('normalizes the Control Plane fixture into shared workspace state', () => {
    const snapshot = createInitialWorkspaceSnapshot('workspace-1');
    expect(snapshot.workspaceId).toBe('workspace-1');
    expect(snapshot.agents.length).toBeGreaterThan(0);
    expect(snapshot.messages.length).toBeGreaterThan(0);
    expect(snapshot.agents[0]).toHaveProperty('id');
  });

  it('carries artifact version history, bodies, and sign-offs without sharing references', () => {
    const snapshot = createInitialWorkspaceSnapshot('workspace-1');
    const artifact = snapshot.artifacts.find((item) => item.id === 'art-01');
    expect(artifact?.versions?.length).toBeGreaterThan(0);
    expect(artifact?.versions?.[0]).toMatchObject({ version: 'v2.3' });
    expect(artifact?.markdownContent).toContain('Real-time Clearing');
    expect(artifact?.acceptedBy).toContain('Agent-01');
    expect(snapshot.artifacts.every((item) => Array.isArray(item.versions))).toBe(true);
  });
});
