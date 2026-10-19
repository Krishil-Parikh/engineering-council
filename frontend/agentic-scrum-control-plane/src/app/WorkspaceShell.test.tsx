import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { WorkspaceProvider } from '../state/WorkspaceProvider';
import { MockWorkspaceRepository } from '../repositories/MockWorkspaceRepository';
import { WorkspaceShell } from './WorkspaceShell';
import { activeSprintWorkspace } from '../test/fixtures/workspaces';

function renderShell() {
  const repository = new MockWorkspaceRepository(activeSprintWorkspace('workspace-demo'));
  render(
    <WorkspaceProvider workspaceId="workspace-demo" repository={repository}>
      <WorkspaceShell />
    </WorkspaceProvider>,
  );
  return repository;
}

describe('WorkspaceShell cross-view integration', () => {
  it('starts on GenUI with the canonical phase', async () => {
    renderShell();
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
  });

  it('keeps sprint, agent, and message state consistent across both views', async () => {
    const repository = renderShell();
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();

    await repository.execute({ type: 'sprint.start', workspaceId: 'workspace-demo', brief: 'Cross-view sprint' });
    expect(await screen.findByText('Full dialogue transcript & debate telemetry')).toBeInTheDocument();

    const agent = (await repository.getSnapshot('workspace-demo')).agents[0];
    repository.emit({
      eventId: 'cross-agent-1',
      workspaceId: 'workspace-demo',
      occurredAt: new Date().toISOString(),
      version: 100,
      type: 'agent.updated',
      payload: { ...agent, status: 'speaking', activeTask: 'Shared task' },
    });
    repository.emit({
      eventId: 'cross-message-1',
      workspaceId: 'workspace-demo',
      occurredAt: new Date().toISOString(),
      version: 101,
      type: 'message.created',
      payload: { id: 'cross-msg-1', meetId: 'meet-1', senderId: 'agent-1', senderName: 'Agent-01', text: 'Cross-view hello', timestamp: '10:01:00' },
    });

    fireEvent.click(screen.getByRole('tab', { name: 'Control Plane' }));
    expect((await screen.findAllByText('Shared task')).length).toBeGreaterThan(0);
    expect(await screen.findByText('Cross-view hello')).toBeInTheDocument();

    await repository.execute({ type: 'sme.directive.submit', workspaceId: 'workspace-demo', meetId: 'meet-1', directive: 'Use Raft' });

    fireEvent.click(screen.getByRole('tab', { name: 'GenUI' }));
    expect(await screen.findByText('Full dialogue transcript & debate telemetry')).toBeInTheDocument();
    fireEvent.click(await screen.findByText('Transcript Log'));
    expect((await screen.findAllByText(/Use Raft/)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText('Cross-view hello')).length).toBeGreaterThan(0);
  });

  it('does not reset workspace state when switching modes', async () => {
    const repository = renderShell();
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
    repository.emit({
      eventId: 'persist-1',
      workspaceId: 'workspace-demo',
      occurredAt: new Date().toISOString(),
      version: 100,
      type: 'message.created',
      payload: { id: 'persist-msg-1', meetId: 'meet-1', senderId: 'agent-2', senderName: 'Agent-02', text: 'Persistent note', timestamp: '10:02:00' },
    });

    fireEvent.click(screen.getByRole('tab', { name: 'Control Plane' }));
    expect(await screen.findByText('Persistent note')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'GenUI' }));
    fireEvent.click(await screen.findByText('Transcript Log'));
    expect(await screen.findByText('Persistent note')).toBeInTheDocument();
  });

  it('supports keyboard navigation between the top-level mode tabs', async () => {
    renderShell();
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('tab', { name: 'GenUI' }), { key: 'ArrowRight' });
    expect(await screen.findByText('LIVE DELEGATION GRAPH')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Control Plane' }), { key: 'ArrowLeft' });
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
  });
});
