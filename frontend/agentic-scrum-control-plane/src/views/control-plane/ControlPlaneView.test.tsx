import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { WorkspaceProvider } from '../../state/WorkspaceProvider';
import { MockWorkspaceRepository } from '../../repositories/MockWorkspaceRepository';
import { WorkspaceControlPlaneView } from './WorkspaceControlPlaneView';
import { activeSprintWorkspace } from '../../test/fixtures/workspaces';
import { createDemoWorkspaceSnapshot } from '../../adapters/createDemoWorkspaceSnapshot';

function renderControlPlaneView() {
  const repository = new MockWorkspaceRepository(activeSprintWorkspace('workspace-demo'));
  render(
    <WorkspaceProvider workspaceId="workspace-demo" repository={repository}>
      <WorkspaceControlPlaneView />
    </WorkspaceProvider>,
  );
  return repository;
}

function renderControlPlaneViewWithDemoSeed() {
  const repository = new MockWorkspaceRepository(createDemoWorkspaceSnapshot('workspace-demo'));
  render(
    <WorkspaceProvider workspaceId="workspace-demo" repository={repository}>
      <WorkspaceControlPlaneView />
    </WorkspaceProvider>,
  );
  return repository;
}

describe('ControlPlaneView', () => {
  it('renders the same canonical agent data as GenUI', async () => {
    renderControlPlaneView();
    expect((await screen.findAllByText('Agent-01')).length).toBeGreaterThan(0);
  });

  it('renders the same canonical message data as GenUI', async () => {
    renderControlPlaneView();
    expect(await screen.findByText('Started')).toBeInTheDocument();
  });

  it('shows reassigned tasks once the shared store updates', async () => {
    const repository = renderControlPlaneView();
    expect((await screen.findAllByText('Agent-01')).length).toBeGreaterThan(0);
    const agent = (await repository.getSnapshot('workspace-demo')).agents[0];
    repository.emit({
      eventId: 'reassign-1',
      workspaceId: 'workspace-demo',
      occurredAt: new Date().toISOString(),
      version: 99,
      type: 'agent.updated',
      payload: { ...agent, status: 'speaking', activeTask: 'Shared task' },
    });
    expect(await screen.findByText('Shared task')).toBeInTheDocument();
  });

  it('keeps presentational tab selection independent from workspace data', async () => {
    renderControlPlaneView();
    expect(await screen.findByText('Started')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Meet — Live Transcript & Debate'));
    expect(await screen.findByText('Started')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Overview — The Command Deck'));
    expect(await screen.findByText('Started')).toBeInTheDocument();
  });

  it('renders the artifacts tab without version history instead of crashing', async () => {
    renderControlPlaneView();
    fireEvent.click(screen.getByLabelText('Artifacts — PRD & Architecture Diffs'));
    expect(await screen.findByText(/DOCUMENTS \(/)).toBeInTheDocument();
    expect((await screen.findAllByText('PRD.md')).length).toBeGreaterThan(0);
    expect(await screen.findByText(/history unavailable in snapshot/)).toBeInTheDocument();
  });

  it('renders full version history and document body from rich snapshots', async () => {
    renderControlPlaneViewWithDemoSeed();
    fireEvent.click(screen.getByLabelText('Artifacts — PRD & Architecture Diffs'));
    expect((await screen.findAllByText('Product Requirement Document')).length).toBeGreaterThan(0);
    expect((await screen.findAllByText('v2.3')).length).toBeGreaterThan(0);
    expect(await screen.findByText(/Diff Summary for v2.3/)).toBeInTheDocument();
    expect(await screen.findByText(/Real-time Clearing/)).toBeInTheDocument();
    expect(screen.queryByText(/history unavailable in snapshot/)).not.toBeInTheDocument();
  });
});
