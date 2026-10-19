import type { WorkspaceCommand, CommandResult } from '../domain/commands';
import { validateWorkspaceCommand } from '../domain/commands';
import type { WorkspaceEvent, WorkspaceSnapshot } from '../domain/types';
import { assertWorkspaceSnapshot } from '../adapters/validateWorkspaceSnapshot';
import type { WorkspaceRepository } from './WorkspaceRepository';

export type EventSourceFactory = (url: string) => EventSource;

export interface HttpRepositoryOptions {
  timeoutMs?: number;
  maxReconnectAttempts?: number;
  reconnectBaseMs?: number;
}

export function mapSnapshotHttpError(status: number): Error {
  if (status === 401) return new Error('Workspace snapshot failed: 401 Unauthorized');
  if (status === 403) return new Error('Workspace snapshot failed: 403 Forbidden');
  if (status === 404) return new Error('Workspace snapshot failed: 404 Not found');
  if (status === 409) return new Error('Workspace snapshot failed: 409 Conflict');
  if (status === 429) return new Error('Workspace snapshot failed: 429 Rate limited');
  return new Error(`Workspace snapshot failed: ${status}`);
}

export class HttpWorkspaceRepository implements WorkspaceRepository {
  private readonly timeoutMs: number;
  private readonly maxReconnectAttempts: number;
  private readonly reconnectBaseMs: number;

  constructor(
    private readonly baseUrl: string,
    private readonly fetcher: typeof fetch = fetch,
    private readonly eventSourceFactory: EventSourceFactory = (url) => new EventSource(url),
    options: HttpRepositoryOptions = {},
  ) {
    this.timeoutMs = options.timeoutMs ?? 10000;
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 5;
    this.reconnectBaseMs = options.reconnectBaseMs ?? 1000;
  }

  private async fetchJson(input: string, init?: RequestInit): Promise<unknown> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetcher(input, { ...init, signal: controller.signal });
      if (!response.ok) throw mapSnapshotHttpError(response.status);
      return await response.json() as unknown;
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error(`Workspace request timed out after ${this.timeoutMs}ms`);
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  async getSnapshot(workspaceId: string): Promise<WorkspaceSnapshot> {
    const data = await this.fetchJson(`${this.baseUrl}/workspace/${encodeURIComponent(workspaceId)}/snapshot`);
    assertWorkspaceSnapshot(data);
    return data;
  }

  async execute(command: WorkspaceCommand): Promise<CommandResult> {
    const validation = validateWorkspaceCommand(command);
    if (!validation.ok) throw new Error(`Invalid command: ${validation.error}`);
    const data = await this.fetchJson(`${this.baseUrl}/workspace/${encodeURIComponent(command.workspaceId)}/commands`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(command),
    });
    if (typeof data !== 'object' || data === null) throw new Error('Workspace command failed: malformed response');
    return data as CommandResult;
  }

  subscribe(workspaceId: string, onEvent: (event: WorkspaceEvent) => void, onError?: (error: Error) => void) {
    let closed = false;
    let attempts = 0;
    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    const seenEventIds = new Set<string>();

    const handleMessage = (message: MessageEvent<string>) => {
      try {
        const event = JSON.parse(message.data) as WorkspaceEvent;
        if (typeof event !== 'object' || event === null || typeof (event as { eventId?: unknown }).eventId !== 'string') {
          onError?.(new Error('Workspace event was malformed'));
          return;
        }
        if (seenEventIds.has(event.eventId)) return;
        seenEventIds.add(event.eventId);
        attempts = 0;
        onEvent(event);
      } catch {
        onError?.(new Error('Workspace event was not valid JSON'));
      }
    };
    const connect = () => {
      if (closed) return;
      source = this.eventSourceFactory(`${this.baseUrl}/workspace/${encodeURIComponent(workspaceId)}/events`);
      source.addEventListener('message', handleMessage as EventListener);
      source.addEventListener('error', handleDisconnect as EventListener);
    };
    const handleDisconnect = () => {
      if (closed) return;
      cleanupSource();
      attempts += 1;
      if (attempts > this.maxReconnectAttempts) {
        onError?.(new Error('Workspace event stream disconnected'));
        return;
      }
      const delay = this.reconnectBaseMs * 2 ** (attempts - 1);
      retryTimer = setTimeout(connect, delay);
    };
    const cleanupSource = () => {
      source?.removeEventListener('message', handleMessage as EventListener);
      source?.removeEventListener('error', handleDisconnect as EventListener);
      source?.close();
      source = null;
    };

    connect();
    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      cleanupSource();
    };
  }
}
