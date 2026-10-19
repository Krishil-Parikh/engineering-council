import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { WorkspaceProvider, useWorkspace } from '../state/WorkspaceProvider';
import type { WorkspaceRepository } from '../repositories/WorkspaceRepository';
import type { CommandResult } from '../domain/commands';
import type { WorkspaceEvent, WorkspaceSnapshot } from '../domain/types';
import { WorkspaceShell } from './WorkspaceShell';
import { activeSprintWorkspace, emptyWorkspace } from '../test/fixtures/workspaces';

type Handler = { onEvent: (event: WorkspaceEvent) => void; onError?: (error: Error) => void };

class FakeRepository implements WorkspaceRepository {
  snapshotError: Error | null = null;
  streamError: Error | null = null;
  executeError: Error | null = null;
  private readonly seed: WorkspaceSnapshot;
  private readonly handlers = new Set<Handler>();

  constructor(seed: WorkspaceSnapshot) {
    this.seed = structuredClone(seed);
  }

  async getSnapshot(workspaceId: string): Promise<WorkspaceSnapshot> {
    if (this.snapshotError) throw this.snapshotError;
    if (workspaceId !== this.seed.workspaceId) throw new Error(`Unknown workspace: ${workspaceId}`);
    return structuredClone(this.seed);
  }

  async execute(): Promise<CommandResult> {
    if (this.executeError) throw this.executeError;
    return { accepted: true, commandId: 'command-1' };
  }

  subscribe(_workspaceId: string, onEvent: (event: WorkspaceEvent) => void, onError?: (error: Error) => void) {
    const handler = { onEvent, onError };
    this.handlers.add(handler);
    if (this.streamError) queueMicrotask(() => onError?.(this.streamError as Error));
    return () => {
      this.handlers.delete(handler);
    };
  }

  failStream(error: Error) {
    this.handlers.forEach((handler) => handler.onError?.(error));
  }
}

function renderShellWith(repository: FakeRepository) {
  render(
    <WorkspaceProvider workspaceId="workspace-demo" repository={repository}>
      <WorkspaceShell />
    </WorkspaceProvider>,
  );
}

function FailCommandButton() {
  const { executeCommand } = useWorkspace();
  return (
    <button
      type="button"
      onClick={() => {
        void executeCommand({ type: 'phase.advance', workspaceId: 'workspace-demo', phaseId: 'build' }).catch(() => undefined);
      }}
    >
      Fail command
    </button>
  );
}

describe('WorkspaceShell resilience states', () => {
  it('shows a loading state while the snapshot resolves', () => {
    const repository = new FakeRepository(activeSprintWorkspace('workspace-demo'));
    const pending = new Promise<WorkspaceSnapshot>(() => undefined);
    repository.getSnapshot = () => pending;
    renderShellWith(repository);
    expect(screen.getByText('Loading workspace…')).toBeInTheDocument();
  });

  it('shows an error state with retry when the snapshot fails', async () => {
    const repository = new FakeRepository(activeSprintWorkspace('workspace-demo'));
    repository.snapshotError = new Error('Workspace snapshot failed: 500');
    renderShellWith(repository);
    expect(await screen.findByText('Workspace snapshot failed: 500')).toBeInTheDocument();
    repository.snapshotError = null;
    fireEvent.click(screen.getByText('Retry'));
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
  });

  it('shows a permission state for unauthorized workspaces', async () => {
    const repository = new FakeRepository(activeSprintWorkspace('workspace-demo'));
    repository.snapshotError = new Error('Workspace snapshot failed: 403 Forbidden');
    renderShellWith(repository);
    expect(await screen.findByText('Workspace snapshot failed: 403 Forbidden')).toBeInTheDocument();
  });

  it('keeps cached state visible with a disconnected banner when the stream drops', async () => {
    const repository = new FakeRepository(activeSprintWorkspace('workspace-demo'));
    renderShellWith(repository);
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
    repository.failStream(new Error('Workspace event stream disconnected'));
    expect(await screen.findByText('Event stream disconnected — showing cached state.')).toBeInTheDocument();
    expect(screen.getByText('PR velocity timeline & build logs')).toBeInTheDocument();
  });

  it('shows a stale banner with refresh when a live update fails', async () => {
    const repository = new FakeRepository(activeSprintWorkspace('workspace-demo'));
    renderShellWith(repository);
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
    repository.failStream(new Error('Workspace event was malformed'));
    expect(await screen.findByText('Workspace event was malformed')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Refresh'));
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
  });

  it('shows an empty state for workspaces without data', async () => {
    const repository = new FakeRepository(emptyWorkspace('workspace-demo'));
    renderShellWith(repository);
    expect(await screen.findByText('This workspace is empty')).toBeInTheDocument();
  });

  it('surfaces command failures without losing workspace state', async () => {
    const repository = new FakeRepository(activeSprintWorkspace('workspace-demo'));
    repository.executeError = new Error('Workspace command failed: 429');
    render(
      <WorkspaceProvider workspaceId="workspace-demo" repository={repository}>
        <WorkspaceShell />
        <FailCommandButton />
      </WorkspaceProvider>,
    );
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Fail command'));
    expect(await screen.findByText('Command failed: Workspace command failed: 429')).toBeInTheDocument();
    expect(screen.getByText('PR velocity timeline & build logs')).toBeInTheDocument();
  });
});
