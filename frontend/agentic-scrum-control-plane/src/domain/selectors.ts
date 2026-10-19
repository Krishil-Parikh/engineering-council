import type { WorkspaceSnapshot } from './types';

export function selectActivePhase(snapshot: WorkspaceSnapshot) {
  return snapshot.phaseId;
}

export function selectAgent(snapshot: WorkspaceSnapshot, agentId: string) {
  return snapshot.agents.find((agent) => agent.id === agentId) ?? null;
}

/** Returns null when the id is stale (agent no longer in the snapshot after refresh). */
export function selectAgentSafe(snapshot: WorkspaceSnapshot, agentId: string | null) {
  if (!agentId) return null;
  return selectAgent(snapshot, agentId);
}

export function selectMeet(snapshot: WorkspaceSnapshot, meetId: string) {
  return snapshot.meets.find((meet) => meet.id === meetId) ?? null;
}

export function selectMeetMessages(snapshot: WorkspaceSnapshot, meetId: string) {
  return snapshot.messages.filter((message) => message.meetId === meetId);
}

export const selectTranscriptForMeet = selectMeetMessages;

export function selectActiveAgents(snapshot: WorkspaceSnapshot) {
  return snapshot.agents.filter((agent) => agent.status !== 'idle');
}

export function selectArtifactAcceptanceRatio(snapshot: WorkspaceSnapshot, artifactId?: string) {
  const artifact = artifactId
    ? snapshot.artifacts.find((item) => item.id === artifactId)
    : snapshot.artifacts[0];
  if (!artifact) return { label: '0/0', ratio: 0 };
  const ratio = artifact.totalRequired === 0 ? 0 : artifact.acceptedCount / artifact.totalRequired;
  return { label: `${artifact.acceptedCount}/${artifact.totalRequired}`, ratio };
}

export function selectCurrentMetrics(snapshot: WorkspaceSnapshot) {
  return snapshot.metrics;
}

export function selectDelegationGraph(snapshot: WorkspaceSnapshot) {
  return {
    nodes: snapshot.agents.map((agent) => ({ id: agent.id, name: agent.name, status: agent.status })),
    edges: snapshot.edges,
    activeEdges: snapshot.edges.filter((edge) => edge.isActive),
  };
}

export function selectIsEmptyWorkspace(snapshot: WorkspaceSnapshot) {
  return (
    snapshot.agents.length === 0 &&
    snapshot.messages.length === 0 &&
    snapshot.artifacts.length === 0 &&
    snapshot.meets.length === 0
  );
}
