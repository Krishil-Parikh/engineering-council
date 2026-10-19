import { applyWorkspaceEvent } from '../domain/reducers';
import type { WorkspaceEvent, WorkspaceSnapshot } from '../domain/types';

export class WorkspaceStore {
  private snapshot: WorkspaceSnapshot;
  private readonly listeners = new Set<() => void>();

  constructor(snapshot: WorkspaceSnapshot) {
    this.snapshot = snapshot;
  }

  getSnapshot = () => this.snapshot;

  replaceSnapshot = (snapshot: WorkspaceSnapshot) => {
    this.snapshot = snapshot;
    this.listeners.forEach((listener) => listener());
  };

  apply = (event: WorkspaceEvent) => {
    const next = applyWorkspaceEvent(this.snapshot, event);
    if (next === this.snapshot) return;
    this.snapshot = next;
    this.listeners.forEach((listener) => listener());
  };

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
}
