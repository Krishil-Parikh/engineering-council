import { describe, expect, it, vi } from 'vitest';
import { startWorkspaceSimulation } from './simulation';
import type { WorkspaceEvent } from '../domain/types';

describe('startWorkspaceSimulation', () => {
  it('emits deterministic demo events on one loop and stops on cleanup', () => {
    vi.useFakeTimers();
    try {
      const emitted: WorkspaceEvent[] = [];
      const stop = startWorkspaceSimulation((event) => emitted.push(event), 'workspace-1', { intervalMs: 1000 });
      expect(emitted).toHaveLength(0);
      vi.advanceTimersByTime(1000);
      expect(emitted).toHaveLength(1);
      expect(emitted[0].workspaceId).toBe('workspace-1');
      expect(emitted[0].type).toBe('message.created');
      vi.advanceTimersByTime(3000);
      expect(emitted).toHaveLength(4);
      stop();
      vi.advanceTimersByTime(5000);
      expect(emitted).toHaveLength(4);
    } finally {
      vi.useRealTimers();
    }
  });
});
