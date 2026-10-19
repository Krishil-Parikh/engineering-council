import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { WorkspaceProvider } from '../../state/WorkspaceProvider';
import { MockWorkspaceRepository } from '../../repositories/MockWorkspaceRepository';
import { GenUIView } from './GenUIView';
import { activeSprintWorkspace } from '../../test/fixtures/workspaces';
import { createDemoWorkspaceSnapshot } from '../../adapters/createDemoWorkspaceSnapshot';

function renderGenUIView() {
  const repository = new MockWorkspaceRepository(activeSprintWorkspace('workspace-demo'));
  render(
    <WorkspaceProvider workspaceId="workspace-demo" repository={repository}>
      <GenUIView />
    </WorkspaceProvider>,
  );
  return repository;
}

function renderGenUIViewWithDemoSeed() {
  const repository = new MockWorkspaceRepository(createDemoWorkspaceSnapshot('workspace-demo'));
  render(
    <WorkspaceProvider workspaceId="workspace-demo" repository={repository}>
      <GenUIView />
    </WorkspaceProvider>,
  );
  return repository;
}

describe('GenUIView', () => {
  it('renders the canonical active phase', async () => {
    renderGenUIView();
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
  });

  it('renders canonical agents with their shared tasks', async () => {
    renderGenUIView();
    fireEvent.click(await screen.findByText('Agent Roster'));
    expect(await screen.findByText('Agent-01')).toBeInTheDocument();
    expect(await screen.findByText('Build API')).toBeInTheDocument();
  });

  it('renders canonical messages in the shared transcript', async () => {
    renderGenUIView();
    fireEvent.click(await screen.findByText('Transcript Log'));
    expect(await screen.findByText('Started')).toBeInTheDocument();
  });

  it('reflects phase commands from the shared store', async () => {
    const repository = renderGenUIView();
    expect(await screen.findByText('PR velocity timeline & build logs')).toBeInTheDocument();
    await repository.execute({ type: 'phase.advance', workspaceId: 'workspace-demo', phaseId: 'review' });
    expect(await screen.findByText('Code audit & test verification report')).toBeInTheDocument();
  });

  it('reflects reassigned tasks from the shared store', async () => {
    const repository = renderGenUIView();
    fireEvent.click(await screen.findByText('Agent Roster'));
    await repository.execute({ type: 'agent.task.reassign', workspaceId: 'workspace-demo', agentId: 'agent-1', task: 'Shared task' });
    expect(await screen.findByText('Shared task')).toBeInTheDocument();
  });

  it('unsticks brainstorm: SME checkpoint and conclude advance to PRD', async () => {
    const repository = renderGenUIViewWithDemoSeed();
    expect(await screen.findByText('Agent roster & standby skills')).toBeInTheDocument();
    await repository.execute({ type: 'sprint.start', workspaceId: 'workspace-demo', brief: 'Test brief' });
    expect(await screen.findByText('Supervisory Checkpoint · Action Required')).toBeInTheDocument();
    expect(await screen.findByText('divergent architectural opinions · live debate')).toBeInTheDocument();
    fireEvent.click(await screen.findByText(/Option A: Mandate Redis/));
    expect(await screen.findByText(/Decision ratified by Business SME/)).toBeInTheDocument();
    fireEvent.click(await screen.findByText(/Conclude Meet 01/));
    expect(await screen.findByText('Artifacts & acceptance signatures')).toBeInTheDocument();
  });
});
