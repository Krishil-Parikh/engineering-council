import { describe, expect, it } from 'vitest';
import {
  selectActiveAgents,
  selectActivePhase,
  selectAgent,
  selectAgentSafe,
  selectArtifactAcceptanceRatio,
  selectCurrentMetrics,
  selectDelegationGraph,
  selectIsEmptyWorkspace,
  selectMeet,
  selectMeetMessages,
} from './selectors';
import { activeSprintWorkspace, emptyWorkspace } from '../test/fixtures/workspaces';

describe('workspace selectors', () => {
  it('reads the active phase, agents, and meets', () => {
    const snapshot = activeSprintWorkspace('workspace-1');
    expect(selectActivePhase(snapshot)).toBe('build');
    expect(selectActiveAgents(snapshot)).toHaveLength(2);
    expect(selectAgent(snapshot, 'agent-1')?.name).toBe('Agent-01');
    expect(selectAgent(snapshot, 'missing')).toBeNull();
    expect(selectMeet(snapshot, 'meet-1')?.title).toBe('Meet 01');
    expect(selectMeetMessages(snapshot, 'meet-1')).toHaveLength(1);
  });

  it('returns null for stale selected agents after a refresh', () => {
    const snapshot = activeSprintWorkspace('workspace-1');
    expect(selectAgentSafe(snapshot, 'agent-1')).not.toBeNull();
    expect(selectAgentSafe(snapshot, 'agent-removed')).toBeNull();
    expect(selectAgentSafe(snapshot, null)).toBeNull();
  });

  it('derives the artifact acceptance ratio', () => {
    const snapshot = activeSprintWorkspace('workspace-1');
    expect(selectArtifactAcceptanceRatio(snapshot)).toEqual({ label: '1/2', ratio: 0.5 });
    expect(selectArtifactAcceptanceRatio(emptyWorkspace(), 'missing')).toEqual({ label: '0/0', ratio: 0 });
  });

  it('derives metrics and the delegation graph', () => {
    const snapshot = activeSprintWorkspace('workspace-1');
    expect(selectCurrentMetrics(snapshot).totalPRs).toBe(3);
    const graph = selectDelegationGraph(snapshot);
    expect(graph.nodes).toHaveLength(2);
    expect(graph.edges).toHaveLength(1);
    expect(graph.activeEdges).toHaveLength(1);
  });

  it('detects empty workspaces', () => {
    expect(selectIsEmptyWorkspace(emptyWorkspace())).toBe(true);
    expect(selectIsEmptyWorkspace(activeSprintWorkspace('workspace-1'))).toBe(false);
  });
});
