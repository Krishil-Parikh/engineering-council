import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { createDemoWorkspaceSnapshot } from '../../../../adapters/createDemoWorkspaceSnapshot';
import { WorkspaceShell } from '../../../../app/WorkspaceShell';
import { MockWorkspaceRepository } from '../../../../repositories/MockWorkspaceRepository';
import { WorkspaceProvider } from '../../../../state/WorkspaceProvider';
import { MockStandupApi } from '../../adapters/mockStandupApi';

let api: MockStandupApi;
afterEach(() => api?.dispose());

async function openStandup(options = { stepMs: 5, autopilotMs: 60 }, layout = 'panels') {
  window.history.replaceState(null, '', `/?layout=${layout}`);
  const repository = new MockWorkspaceRepository(createDemoWorkspaceSnapshot('workspace-demo'));
  api = new MockStandupApi(options);
  (repository as unknown as { standup: MockStandupApi }).standup = api;
  render(<WorkspaceProvider workspaceId="workspace-demo" repository={repository}><WorkspaceShell /></WorkspaceProvider>);
  await userEvent.click(await screen.findByRole('tab', { name: 'Standup' }));
  await screen.findByTestId('standup-view');
}

describe('the Standup tab in the workspace', () => {
  it('opens next to the other views and goes straight to the meeting that is waiting for the Business SME', async () => {
    await openStandup();
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['GenUI', 'Control Plane', 'Standup']);
    expect(await screen.findByRole('heading', { level: 1, name: 'Sprint 1 planning' })).toBeInTheDocument();
    expect(screen.getByTestId('meeting-status')).toHaveTextContent('Waiting for the Business SME');
    expect(screen.getByTestId('participant-count')).toHaveTextContent('10'); // eight developers: the screen assumed no number
    expect(screen.getAllByTestId('skill-badge').filter((b) => b.textContent === 'Backend').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByTestId('role-badge').map((b) => b.textContent).sort()).toEqual(['adversarial reviewer', 'alternative designer']);
    const rows = screen.getAllByTestId('meeting-row');
    expect(rows.map((r) => r.textContent)).toEqual([expect.stringContaining('Discovery: Jarvis timers and reminders'), expect.stringContaining('Sprint 1 planning')]);
    expect(rows[1]).toHaveTextContent('1 waiting for you');
    const blocked = screen.getAllByTestId('participant-card').find((c) => c.getAttribute('data-status') === 'blocked')!;
    expect(blocked).toHaveTextContent('Developer 03');
  });

  it('does not float the decision card over the Standup panels that show the same questions', async () => {
    const { LiveFakeRepository, idleLiveWorkspace } = await import('../../../../test/liveRepository');
    const repository = new LiveFakeRepository(idleLiveWorkspace('workspace-live'));
    api = new MockStandupApi();
    (repository as unknown as { standup: MockStandupApi }).standup = api;
    render(<WorkspaceProvider workspaceId="workspace-live" repository={repository}><WorkspaceShell /></WorkspaceProvider>);
    await screen.findByRole('tab', { name: 'GenUI' }); // the workspace has loaded and is listening
    repository.message({ id: 'q-msg', text: 'Add a dependency?', kind: 'question', question: { id: 'q-1', context: '', kind: 'approval', options: ['Approve', 'Decline'] } });
    await userEvent.click(screen.getByRole('tab', { name: 'Control Plane' }));
    await screen.findByRole('region', { name: 'Decisions waiting for you' }); // in the other views it floats over the page
    await userEvent.click(await screen.findByRole('tab', { name: 'Standup' }));
    await screen.findByTestId('standup-view');
    expect(screen.queryByRole('region', { name: 'Decisions waiting for you' })).not.toBeInTheDocument();
  });

  it('carries on after the question is answered: the decision is made, the action item appears, the meeting finishes', async () => {
    await openStandup();
    const panel = await screen.findByTestId('question-panel');
    expect(within(panel).getByText('Is a limit of 10 timers right?')).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole('button', { name: '10 (recommended)' }));
    await waitFor(() => expect(screen.getByTestId('meeting-status')).toHaveTextContent('Finished'));
    expect(screen.getByText('Nothing is waiting for the Business SME.')).toBeInTheDocument();
    expect(screen.getAllByTestId('decision').map((d) => d.getAttribute('data-status'))).toEqual(['accepted']);
    expect(screen.getByTestId('decision')).toHaveTextContent('Sprint 1: contracts, router and timer plugin in parallel');
    expect(screen.getByTestId('action-item')).toHaveTextContent('Freeze the Clock, Tick and announce interfaces today');
    expect(screen.getAllByTestId('timeline-entry').some((e) => /Answer/.test(e.textContent ?? ''))).toBe(true);
  });

  it('is answered by the autopilot when the Business SME hands the meeting over, and says who answered', async () => {
    await openStandup();
    await screen.findByTestId('question-panel');
    await userEvent.click(screen.getByRole('radio', { name: 'Autopilot SME' }));
    await waitFor(() => expect(screen.getByTestId('control-mode')).toHaveTextContent('Autopilot Business SME'));
    await waitFor(() => expect(screen.getByTestId('meeting-status')).toHaveTextContent('Finished'), { timeout: 4000 });
    expect(screen.getByRole('radio', { name: 'Autopilot SME' })).toHaveAttribute('aria-checked', 'true');
  });

  it('stays with the person when they take control back before the autopilot answers', async () => {
    await openStandup({ stepMs: 5, autopilotMs: 400 });
    await screen.findByTestId('question-panel');
    await userEvent.click(screen.getByRole('radio', { name: 'Autopilot SME' }));
    await userEvent.click(screen.getByRole('radio', { name: 'I answer' }));
    await new Promise((r) => setTimeout(r, 700));
    expect(screen.getByTestId('meeting-status')).toHaveTextContent('Waiting for the Business SME');
    expect(screen.getByTestId('question-card')).toBeInTheDocument();
  });

  it('replays the finished discovery meeting and jumps to its decision and its question', async () => {
    await openStandup();
    await userEvent.click(await screen.findByRole('button', { name: /Discovery: Jarvis timers and reminders/ }));
    await waitFor(() => expect(screen.getByTestId('meeting-status')).toHaveTextContent('Finished'));
    expect(screen.getAllByTestId('participant-card')).toHaveLength(8);
    expect(screen.queryAllByTestId('skill-badge')).toHaveLength(0); // meeting 1: six generic developers
    await userEvent.click(screen.getByRole('button', { name: 'Replay this meeting' }));
    await screen.findByTestId('replay-controls');
    await userEvent.click(screen.getByRole('button', { name: 'Next question' }));
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent(/event \d+ of 36/));
    const atQuestion = Number(/event (\d+)/.exec(screen.getByTestId('replay-position').textContent ?? '')![1]);
    await waitFor(() => expect(screen.getByTestId('question-card')).toBeInTheDocument()); // the question is open at that moment of the meeting
    await userEvent.click(screen.getByRole('button', { name: 'Next decision' }));
    await waitFor(() => expect(Number(/event (\d+)/.exec(screen.getByTestId('replay-position').textContent ?? '')![1])).toBeGreaterThan(atQuestion));
    await userEvent.click(screen.getByRole('button', { name: 'Back to live' }));
    expect(screen.getByRole('button', { name: 'Replay this meeting' })).toBeInTheDocument();
  });

  it('shows the transcript the backend wrote', async () => {
    await openStandup();
    await userEvent.click(await screen.findByRole('button', { name: /Discovery: Jarvis timers and reminders/ }));
    await waitFor(() => expect(screen.getByTestId('meeting-status')).toHaveTextContent('Finished'));
    await userEvent.click(screen.getByRole('button', { name: 'Open transcript' }));
    const text = (await screen.findByTestId('transcript-text')).textContent ?? '';
    expect(text).toContain('Meeting created: Discovery: Jarvis timers and reminders');
    expect(text).toContain('Developer 04 — Challenge to Developer 03:');
    expect(text).toContain('Decision accepted: Alerts wait while Jarvis speaks or listens -> wait');
  });
});
