import type { WorkspaceSnapshot } from '../domain/types';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function isWorkspaceSnapshot(value: unknown): value is WorkspaceSnapshot {
  if (!isRecord(value)) return false;
  return (
    typeof value.workspaceId === 'string' &&
    typeof value.version === 'number' &&
    typeof value.phaseId === 'string' &&
    Array.isArray(value.agents) &&
    Array.isArray(value.messages) &&
    Array.isArray(value.artifacts) &&
    Array.isArray(value.meets) &&
    Array.isArray(value.processedEventIds) &&
    isRecord(value.metrics)
  );
}

export function assertWorkspaceSnapshot(value: unknown): asserts value is WorkspaceSnapshot {
  if (!isWorkspaceSnapshot(value)) throw new Error('Workspace snapshot failed validation');
}
