import type { WorkspaceEvent, WorkspaceSnapshot } from './types';

function upsert<T extends { id: string }>(items: T[], payload: T): T[] {
  const index = items.findIndex((item) => item.id === payload.id);
  if (index === -1) return [...items, payload];
  return items.map((item) => (item.id === payload.id ? payload : item));
}

const MAX_PROCESSED_EVENT_IDS = 500;

export function applyWorkspaceEvent(snapshot: WorkspaceSnapshot, event: WorkspaceEvent): WorkspaceSnapshot {
  if (event.workspaceId !== snapshot.workspaceId) return snapshot;
  if (snapshot.processedEventIds.includes(event.eventId)) return snapshot;
  if (event.version < snapshot.version) return snapshot;

  const processedEventIds = [...snapshot.processedEventIds, event.eventId];
  const trimmed = processedEventIds.length > MAX_PROCESSED_EVENT_IDS
    ? processedEventIds.slice(processedEventIds.length - MAX_PROCESSED_EVENT_IDS)
    : processedEventIds;

  const next: WorkspaceSnapshot = {
    ...snapshot,
    version: Math.max(snapshot.version, event.version),
    processedEventIds: trimmed,
  };

  switch (event.type) {
    case 'agent.updated': {
      const existing = snapshot.agents.find((agent) => agent.id === event.payload.id);
      return {
        ...next,
        agents: upsert(snapshot.agents, existing ? { ...existing, ...event.payload } : event.payload),
      };
    }
    case 'message.created':
      if (snapshot.messages.some((message) => message.id === event.payload.id)) return snapshot;
      return { ...next, messages: [...snapshot.messages, event.payload] };
    case 'phase.changed':
      if (snapshot.phaseId === event.payload.phaseId) return { ...next };
      return { ...next, phaseId: event.payload.phaseId };
    case 'artifact.updated':
      return { ...next, artifacts: upsert(snapshot.artifacts, event.payload) };
    case 'meet.updated':
      return { ...next, meets: upsert(snapshot.meets, event.payload) };
    case 'metrics.updated':
      return { ...next, metrics: event.payload };
    case 'skill.updated':
      return { ...next, skills: upsert(snapshot.skills, event.payload) };
    case 'sprint.updated':
      return { ...next, sprints: upsert(snapshot.sprints, event.payload) };
    case 'edge.updated':
      return { ...next, edges: upsert(snapshot.edges, event.payload) };
  }
}
