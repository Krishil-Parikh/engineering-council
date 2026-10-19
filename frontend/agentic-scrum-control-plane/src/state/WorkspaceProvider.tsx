import React, { createContext, useCallback, useContext, useEffect, useSyncExternalStore } from 'react';
import type { WorkspaceRepository } from '../repositories/WorkspaceRepository';
import { WorkspaceStore } from './workspaceStore';
import type { WorkspaceEvent, WorkspaceSnapshot } from '../domain/types';
import type { CommandResult, WorkspaceCommand } from '../domain/commands';

export type WorkspaceStatus =
  | 'loading'
  | 'ready'
  | 'error'
  | 'disconnected'
  | 'permission-denied'
  | 'stale';

export type StreamHealth = 'unknown' | 'connected' | 'disconnected';

interface WorkspaceContextValue {
  snapshot: WorkspaceSnapshot;
  repository: WorkspaceRepository;
  publishEvent: (event: WorkspaceEvent) => void;
  executeCommand: (command: WorkspaceCommand) => Promise<CommandResult>;
  status: WorkspaceStatus;
  error: Error | null;
  streamHealth: StreamHealth;
  lastEventAt: string | null;
  commandError: Error | null;
  retry: () => void;
  refresh: () => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function mapSnapshotErrorToStatus(error: unknown): { status: WorkspaceStatus; error: Error } {
  const normalized = error instanceof Error ? error : new Error('Workspace snapshot failed');
  if (/401 Unauthorized|403 Forbidden/.test(normalized.message)) {
    return { status: 'permission-denied', error: normalized };
  }
  return { status: 'error', error: normalized };
}

export function WorkspaceProvider({
  workspaceId,
  repository,
  children,
}: {
  workspaceId: string;
  repository: WorkspaceRepository;
  children: React.ReactNode;
}) {
  const [store] = React.useState(() => new WorkspaceStore({
    workspaceId,
    version: 0,
    phaseId: 'kickoff',
    agents: [],
    messages: [],
    skills: [],
    artifacts: [],
    meets: [],
    sprints: [],
    edges: [],
    metrics: { totalMessagesToday: 0, totalPRs: 0, prHistory: [] },
    processedEventIds: [],
  }));
  const [status, setStatus] = React.useState<WorkspaceStatus>('loading');
  const [error, setError] = React.useState<Error | null>(null);
  const [streamHealth, setStreamHealth] = React.useState<StreamHealth>('unknown');
  const [lastEventAt, setLastEventAt] = React.useState<string | null>(null);
  const [commandError, setCommandError] = React.useState<Error | null>(null);
  const [attempt, setAttempt] = React.useState(0);
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const hasSnapshot = React.useRef(false);

  useEffect(() => {
    let active = true;
    let unsubscribe: (() => void) | undefined;
    setStatus('loading');
    setError(null);
    // Load first, then subscribe: no live event can arrive before the
    // baseline snapshot exists, so nothing is ever wiped by the initial load.
    void repository.getSnapshot(workspaceId).then((next) => {
      if (!active) return;
      store.replaceSnapshot(next);
      hasSnapshot.current = true;
      setStatus('ready');
      setStreamHealth('connected');
      unsubscribe = repository.subscribe(workspaceId, (event) => {
        store.apply(event);
        setLastEventAt(event.occurredAt);
        setStreamHealth('connected');
        setStatus((current) => (current === 'disconnected' ? 'ready' : current));
      }, (nextError) => {
        setStreamHealth('disconnected');
        if (/disconnected/i.test(nextError.message)) {
          setError(nextError);
          setStatus((current) => (current === 'ready' || current === 'stale' ? 'disconnected' : current));
        } else {
          setError(nextError);
          setStatus((current) => (current === 'ready' ? 'stale' : 'error'));
        }
      });
    }).catch((nextError: unknown) => {
      if (!active) return;
      if (hasSnapshot.current) {
        setError(nextError instanceof Error ? nextError : new Error('Workspace refresh failed'));
        setStatus('stale');
        return;
      }
      const mapped = mapSnapshotErrorToStatus(nextError);
      setError(mapped.error);
      setStatus(mapped.status);
    });
    return () => {
      active = false;
      unsubscribe?.();
    };
  }, [repository, store, workspaceId, attempt]);

  const executeCommand = useCallback(async (command: WorkspaceCommand) => {
    setCommandError(null);
    try {
      return await repository.execute(command);
    } catch (nextError) {
      const normalized = nextError instanceof Error ? nextError : new Error('Workspace command failed');
      setCommandError(normalized);
      throw normalized;
    }
  }, [repository]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const refresh = useCallback(() => {
    let active = true;
    void repository.getSnapshot(workspaceId).then((next) => {
      if (!active) return;
      store.replaceSnapshot(next);
      hasSnapshot.current = true;
      setStatus('ready');
      setError(null);
    }).catch((nextError: unknown) => {
      if (!active) return;
      setError(nextError instanceof Error ? nextError : new Error('Workspace refresh failed'));
      setStatus('stale');
    });
    return () => {
      active = false;
    };
  }, [repository, store, workspaceId]);

  return (
    <WorkspaceContext.Provider value={{
      snapshot, repository, publishEvent: store.apply, executeCommand,
      status, error, streamHealth, lastEventAt, commandError, retry, refresh,
    }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error('useWorkspace must be used within WorkspaceProvider');
  return context;
}
