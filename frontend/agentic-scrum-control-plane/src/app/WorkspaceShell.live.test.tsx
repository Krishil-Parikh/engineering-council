import { describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { WorkspaceProvider } from '../state/WorkspaceProvider';
import { MockWorkspaceRepository } from '../repositories/MockWorkspaceRepository';
import { WorkspaceShell } from './WorkspaceShell';
import { LiveFakeRepository, idleLiveWorkspace } from '../test/liveRepository';
import { activeSprintWorkspace } from '../test/fixtures/workspaces';

const WORKSPACE = 'workspace-live';

function renderLiveShell() {
  const repository = new LiveFakeRepository({
    ...idleLiveWorkspace(WORKSPACE),
    agents: [
      { id: 'agent-sm', name: 'Scrum Master', role: 'Scrum Master', status: 'idle' },
      { id: 'sme-01', name: 'SME-01', role: 'Business SME (you)', status: 'idle' },
      { id: 'agent-01', name: 'DEV_1', role: 'Backend Developer', status: 'active', activeTask: 'database-module', claimedSkill: 'Backend' },
    ],
    meets: [{ id: 'meet-01', title: 'Kickoff meeting: Habitly', status: 'live', consensusRate: 0, debateIntensity: 0 }],
  });
  render(
    <WorkspaceProvider workspaceId={WORKSPACE} repository={repository}>
      <WorkspaceShell />
    </WorkspaceProvider>,
  );
  return repository;
}

const approvalCard = {
  id: 'm-approval', kind: 'question' as const, text: 'Design change: use a cache', meetId: 'meet-decisions',
  question: { id: 'APP-002', kind: 'approval' as const, context: 'DEV_3 proposes a read-through cache.\n\nThe team voted: DEV_1 approve', options: ['Approve', 'Decline'] },
};

describe('decisions the team needs from you', () => {
  it('appear in whichever view you are in, and answering sends the question id', async () => {
    const repository = renderLiveShell();
    await screen.findByRole('tab', { name: 'GenUI' });
    act(() => repository.message(approvalCard));
    const panel = await screen.findByRole('region', { name: 'Decisions waiting for you' });
    expect(within(panel).getByText('Design change: use a cache')).toBeInTheDocument();
    expect(within(panel).getByText(/DEV_3 proposes a read-through cache/)).toBeInTheDocument();
    fireEvent.change(within(panel).getByLabelText('Your answer'), { target: { value: 'not needed yet' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Decline' }));
    await waitFor(() => expect(repository.commands).toHaveLength(1));
    expect(repository.commands[0]).toMatchObject({ type: 'sme.directive.submit', directive: 'Decline: not needed yet', questionId: 'APP-002', meetId: 'meet-decisions' });
    act(() => repository.message({ id: 'm-answer', kind: 'answer', answersQuestion: 'APP-002', text: 'Decline: not needed yet', senderId: 'sme-01', senderName: 'SME-01' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Decisions waiting for you' })).not.toBeInTheDocument());
  });

  it('are also shown in the control plane, where accepting the documents is a prd.accept', async () => {
    const repository = renderLiveShell();
    await screen.findByRole('tab', { name: 'GenUI' });
    act(() => repository.message({
      id: 'm-docs', kind: 'question', text: 'Accept the project documents?', meetId: 'meet-prd',
      question: { id: 'APP-001', kind: 'documents', context: 'Read these first', options: ['Approve', 'Decline'] },
    }));
    expect(screen.queryByRole('region', { name: 'Decisions waiting for you' })).not.toBeInTheDocument(); // the GenUI screen shows documents itself
    fireEvent.click(screen.getByRole('tab', { name: 'Control Plane' }));
    const panel = await screen.findByRole('region', { name: 'Decisions waiting for you' });
    fireEvent.click(within(panel).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(repository.commandsOfType('prd.accept')).toHaveLength(1));
  });
});

describe('the control plane with a real team', () => {
  it('has no demo loop, and the debate button asks you what to say instead of sending canned text', async () => {
    const repository = renderLiveShell();
    fireEvent.click(await screen.findByRole('tab', { name: 'Control Plane' }));
    await screen.findByTitle('Inject an architectural challenge into the active meet');
    expect(screen.queryByTitle('Step next agent message & pulse')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Pause Automated Loop')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Inject an architectural challenge into the active meet'));
    expect(await screen.findByText('Business SME Intervention')).toBeInTheDocument();
    expect(repository.commandsOfType('debate.inject')).toHaveLength(0);
  });

  it('sends your directive for the meet that exists, not a hard-coded demo meet', async () => {
    const repository = renderLiveShell();
    fireEvent.click(await screen.findByRole('tab', { name: 'Control Plane' }));
    fireEvent.click(await screen.findByTitle('Inject an architectural challenge into the active meet'));
    fireEvent.change(await screen.findByPlaceholderText(/e.g. Ingestion engine/), { target: { value: 'Keep the API stable.' } });
    fireEvent.click(screen.getByText('Broadcast Directive'));
    await waitFor(() => expect(repository.commandsOfType('sme.directive.submit')).toHaveLength(1));
    expect(repository.commands[0]).toMatchObject({ directive: 'Keep the API stable.', meetId: 'meet-01' });
  });

  it('shows the real project and numbers, and none of the demo content', async () => {
    const repository = renderLiveShell();
    fireEvent.click(await screen.findByRole('tab', { name: 'Control Plane' }));
    await screen.findByTitle('Inject an architectural challenge into the active meet');
    act(() => {
      repository.phase('build');
      repository.metrics({ totalMessagesToday: 4, totalPRs: 2, prHistory: [] });
    });
    await waitFor(() => expect(screen.getAllByText('Habitly').length).toBeGreaterThan(0));
    for (const demo of [/Fintech Clearing/, /FINMA/, /AUTOPILOT/, /Elapsed/, /4\.2k tok/, /Kafka/, /Zurich/, /2h 14m/, /Raft/]) {
      expect(screen.queryByText(demo)).not.toBeInTheDocument();
    }
    expect(screen.getByText('FEATURES MERGED')).toBeInTheDocument();
    expect(screen.getByText('2 features merged')).toBeInTheDocument();
  });

  it('shows the live terminal of the agent you click, and it keeps updating', async () => {
    const repository = renderLiveShell();
    fireEvent.click(await screen.findByRole('tab', { name: 'Control Plane' }));
    await screen.findByTitle('Inject an architectural challenge into the active meet');
    fireEvent.click(screen.getAllByText('DEV_1')[0]);
    expect(await screen.findByRole('log', { name: 'Live terminal: DEV_1' })).toHaveTextContent('Waiting for DEV_1');
    act(() => repository.agent({ id: 'agent-01', name: 'DEV_1', role: 'Backend Developer', status: 'active', terminal: ['10:00:01 $ pytest -q'] }));
    await waitFor(() => expect(screen.getByRole('log', { name: 'Live terminal: DEV_1' })).toHaveTextContent('$ pytest -q'));
    act(() => repository.agent({ id: 'agent-01', name: 'DEV_1', role: 'Backend Developer', status: 'active', terminal: ['10:00:01 $ pytest -q', '10:00:09   exit 0'] }));
    await waitFor(() => expect(screen.getByRole('log', { name: 'Live terminal: DEV_1' })).toHaveTextContent('exit 0'));
  });

  it('keeps the demo loop controls in the demo', async () => {
    render(
      <WorkspaceProvider workspaceId="workspace-demo" repository={new MockWorkspaceRepository(activeSprintWorkspace('workspace-demo'))}>
        <WorkspaceShell />
      </WorkspaceProvider>,
    );
    fireEvent.click(await screen.findByRole('tab', { name: 'Control Plane' }));
    expect(await screen.findByTitle('Step next agent message & pulse')).toBeInTheDocument();
  });
});
