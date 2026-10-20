import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { StandupQuestion } from '../../models/standup';
import { StandupView } from '../../components/StandupView';
import { FakeStandupApi, developers, entry, makeView, person, renderStandup, row, wire } from '../helpers';

const question = (over: Partial<StandupQuestion> = {}): StandupQuestion => ({
  question_id: 'q1', meeting_id: 'kickoff', asked_by: 'dev-2', target: 'business_sme', text: 'Should timers survive a restart?', status: 'open', answer: null, answered_by: null,
  options: ['Yes, persist them', 'No, memory only'], recommended: 'No, memory only', asked_at: null, answered_at: null, ...over,
});

async function shown(api: FakeStandupApi) {
  const view = renderStandup(api);
  await screen.findByTestId('meeting-header');
  return view;
}

describe('who is in the meeting', () => {
  it('says so when nobody has joined', async () => {
    await shown(new FakeStandupApi().with(makeView({ participants: [] })));
    expect(screen.getByText('Nobody has joined this meeting yet.')).toBeInTheDocument();
    expect(screen.queryAllByTestId('participant-card')).toHaveLength(0);
    expect(screen.getByTestId('participant-count')).toHaveTextContent('0');
  });

  it.each([[6], [8], [13]])('shows %i developers beside the scrum master and the Business SME, each told apart', async (count) => {
    const participants = [person('sme', 'Business SME', 'business_sme'), person('sm', 'Scrum Master', 'scrum_master'), ...developers(count)];
    await shown(new FakeStandupApi().with(makeView({ participants })));
    expect(screen.getAllByTestId('participant-card')).toHaveLength(count + 2);
    expect(screen.getByTestId('participant-count')).toHaveTextContent(String(count + 2));
    expect(screen.getByText(`Developer ${String(count).padStart(2, '0')}`)).toBeInTheDocument();
    const avatars = screen.getAllByTestId('participant-card').map((card) => card.querySelector('[aria-hidden]')?.textContent);
    expect(new Set(avatars).size).toBe(count + 2); // D1..D13, SM, SM(e): no two look alike
  });

  it('shows people who joined or left while the meeting ran, those who left last and dimmed', async () => {
    const api = new FakeStandupApi().with(makeView({ participants: [person('a', 'Ada'), person('b', 'Bob', 'developer', { status: 'left' }), person('c', 'Cy')] }));
    await shown(api);
    const names = screen.getAllByTestId('participant-card').map((c) => c.querySelector('span.truncate')?.textContent);
    expect(names).toEqual(['Ada', 'Cy', 'Bob']);
    expect(screen.getByTestId('participant-count')).toHaveTextContent('2');
  });

  it('shows skills and temporary roles as labels of this meeting, not as kinds of developer', async () => {
    const participants = [
      person('sme', 'Business SME', 'business_sme'),
      ...developers(4, (i) => ({ skill: i <= 2 ? 'backend' : i === 3 ? 'database' : null, role: i === 2 ? 'adversarial reviewer' : null })),
    ];
    await shown(new FakeStandupApi().with(makeView({ participants })));
    const badges = screen.getAllByTestId('skill-badge').map((b) => b.textContent);
    expect(badges).toEqual(['Backend', 'Backend', 'Database']); // two developers hold the same skill
    expect(screen.getByTestId('role-badge')).toHaveTextContent('adversarial reviewer');
    expect(screen.getAllByTestId('participant-card')[4]).not.toHaveTextContent(/Backend|Database/); // the fourth has no skill: nothing is assumed
  });

  it('shows the same developer with another skill in another meeting', async () => {
    const first = makeView({ meeting_id: 'one', title: 'Meeting one', participants: developers(2, (i) => ({ skill: i === 1 ? 'backend' : null })) });
    const second = makeView({ meeting_id: 'two', title: 'Meeting two', participants: developers(2, (i) => ({ skill: i === 1 ? 'database' : null })) });
    const api = new FakeStandupApi().with(first).with(second);
    renderStandup(api);
    await userEvent.click(await screen.findByRole('button', { name: /Meeting one/ }));
    await waitFor(() => expect(screen.getByTestId('skill-badge')).toHaveTextContent('Backend'));
    await userEvent.click(screen.getByRole('button', { name: /Meeting two/ }));
    await waitFor(() => expect(screen.getByTestId('skill-badge')).toHaveTextContent('Database'));
  });

  it('marks who is speaking, who is waiting for an answer, who is blocked and who needs the Business SME', async () => {
    const participants = [
      person('sme', 'Business SME', 'business_sme', { status: 'needs_sme', needs_sme: true }),
      person('a', 'Speaker', 'developer', { status: 'speaking', speaking: true }),
      person('b', 'Asker', 'developer', { status: 'waiting' }),
      person('c', 'Stuck', 'developer', { status: 'blocked' }),
      person('d', 'Quiet', 'developer'),
    ];
    await shown(new FakeStandupApi().with(makeView({ participants })));
    expect(screen.getAllByTestId('speaker-indicator')).toHaveLength(1);
    expect(screen.getByRole('img', { name: 'speaking' })).toBeInTheDocument();
    const card = (name: string) => screen.getAllByTestId('participant-card').find((c) => c.textContent?.includes(name))!;
    const status = (name: string) => card(name).getAttribute('data-status');
    expect([status('Business SME'), status('Speaker'), status('Asker'), status('Stuck'), status('Quiet')]).toEqual(['needs_sme', 'speaking', 'waiting', 'blocked', 'listening']);
    expect(within(card('Business SME')).getByText('Needs you')).toBeInTheDocument();
    expect(within(card('Asker')).getByText('Waiting for an answer')).toBeInTheDocument();
    expect(card('Speaker')).toHaveAccessibleName(/Speaking/);
  });
});

describe('the conversation', () => {
  it('shows statements, challenges, questions and interventions with who said them and what kind they are', async () => {
    const recent = [
      entry(4, 'statement', 'Keep one process.'),
      entry(5, 'challenge', 'to Developer 01: We do not know the traffic.', { actor_id: 'dev-3', actor_name: 'Developer 03', tone: 'warn' }),
      entry(6, 'clarification_requested', 'Should timers survive a restart?', { tone: 'ask' }),
      entry(7, 'facilitator_intervention', 'Let us settle the alert rule first.', { actor_name: 'Scrum Master', actor_id: 'sm', tone: 'info' }),
    ];
    await shown(new FakeStandupApi().with(makeView({ recent, last_sequence: 7 })));
    const log = screen.getByRole('log', { name: 'Meeting conversation' }.name ? undefined : undefined) ?? screen.getByTestId('timeline');
    expect(log).toHaveAttribute('aria-live', 'polite');
    const entries = screen.getAllByTestId('timeline-entry');
    expect(entries.map((e) => e.getAttribute('data-kind'))).toEqual(['statement', 'challenge', 'clarification_requested', 'facilitator_intervention']);
    expect(within(entries[1]).getByText('Developer 03')).toBeInTheDocument();
    expect(within(entries[1]).getByText('Challenge')).toBeInTheDocument();
    expect(within(entries[1]).getByText(/We do not know the traffic/)).toBeInTheDocument();
    expect(within(entries[2]).getByText('Question for the SME')).toBeInTheDocument();
    expect(within(entries[3]).getByText('Facilitator')).toBeInTheDocument();
  });

  it('keeps joins and setup out of the conversation unless asked for, and says how many there are', async () => {
    const recent = [entry(1, 'meeting_created', 'Meeting created'), entry(2, 'participant_joined', 'Developer 01 joined as developer'), entry(3, 'statement', 'Keep one process.'), entry(4, 'skill_selected', 'Developer 01 took the skill backend')];
    await shown(new FakeStandupApi().with(makeView({ recent, last_sequence: 4 })));
    expect(screen.getAllByTestId('timeline-entry').map((e) => e.getAttribute('data-kind'))).toEqual(['statement']);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Show joins and setup (3)' }));
    expect(screen.getAllByTestId('timeline-entry')).toHaveLength(4);
  });

  it('says so when nothing has been said, and opens the transcript in a dialog that closes', async () => {
    const api = new FakeStandupApi().with(makeView({ recent: [] }));
    await shown(api);
    expect(screen.getByText('Nothing has been said yet.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open transcript' }));
    const dialog = await screen.findByRole('dialog', { name: 'Transcript' });
    expect(within(dialog).getByTestId('transcript-text')).toHaveTextContent('Developer 01 — Statement');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows the current topic, and hides it when the meeting is over', async () => {
    await shown(new FakeStandupApi().with(makeView({ current_topic: 'Settle the alert rule' })));
    expect(screen.getByTestId('current-topic')).toHaveTextContent('Settle the alert rule');
    await vi.waitFor(() => undefined);
  });

  it('renders text from people as text, never as markup', async () => {
    const evil = '<img src=x onerror="window.pwned=1"><script>window.pwned=1</script>';
    await shown(new FakeStandupApi().with(makeView({ recent: [entry(4, 'statement', evil, { actor_name: '<b>Mallory</b>' })], title: '<i>Title</i>' })));
    expect(screen.getByText(evil)).toBeInTheDocument();
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('img[src="x"]')).toBeNull();
    expect((window as unknown as { pwned?: number }).pwned).toBeUndefined();
  });
});

describe('the Business SME', () => {
  it('sees a waiting question with its options and answers it with one click', async () => {
    const q = question();
    const api = new FakeStandupApi().with(makeView({ status: 'waiting_for_sme', open_questions: [q], pending_question: q }));
    await shown(api);
    expect(screen.getByTestId('meeting-status')).toHaveTextContent('Waiting for the Business SME');
    expect(screen.getByTestId('open-question-count')).toHaveTextContent('1');
    expect(screen.getByText('Should timers survive a restart?')).toBeInTheDocument();
    expect(screen.getByText('Developer 02 asks')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No, memory only (recommended)' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, persist them' }));
    await waitFor(() => expect(api.called('answer')).toHaveLength(1));
    expect(api.called('answer')[0].args).toEqual(['kickoff', 'q1', 'Yes, persist them']);
  });

  it('can answer in their own words, and not with an empty answer', async () => {
    const q = question({ options: [] });
    const api = new FakeStandupApi().with(makeView({ status: 'waiting_for_sme', open_questions: [q] }));
    await shown(api);
    const send = screen.getByRole('button', { name: 'Answer' });
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Your answer'), 'Only until restart{enter}');
    await waitFor(() => expect(api.called('answer')[0].args).toEqual(['kickoff', 'q1', 'Only until restart']));
  });

  it('is told when an answer failed, and the question stays', async () => {
    const q = question();
    const api = new FakeStandupApi().with(makeView({ status: 'waiting_for_sme', open_questions: [q] }));
    api.failAnswer = 'That question is no longer waiting for you.';
    await shown(api);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, persist them' }));
    expect(await screen.findByText(/no longer waiting for you/)).toBeInTheDocument();
    expect(screen.getByTestId('question-card')).toBeInTheDocument();
  });

  it('does not offer to answer once the meeting is over', async () => {
    const q = question();
    await shown(new FakeStandupApi().with(makeView({ status: 'completed', open_questions: [q] })));
    expect(screen.getByRole('button', { name: 'Yes, persist them' })).toBeDisabled();
    expect(screen.getByPlaceholderText('This meeting is over')).toBeDisabled();
  });

  it('hands the meeting to the autopilot and takes it back, with a plain statement of what the autopilot will not do', async () => {
    const api = new FakeStandupApi().with(makeView());
    await shown(api);
    const group = screen.getByRole('radiogroup', { name: 'Who answers product questions' });
    expect(within(group).getByRole('radio', { name: 'I answer' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(within(group).getByRole('radio', { name: 'Autopilot SME' }));
    await waitFor(() => expect(api.called('setControl')[0].args).toEqual(['autopilot']));
    await waitFor(() => expect(within(group).getByRole('radio', { name: 'Autopilot SME' })).toHaveAttribute('aria-checked', 'true'));
    expect(screen.getByText(/Documents and approvals still wait for you/)).toBeInTheDocument();
    expect(screen.getByTestId('control-mode')).toHaveTextContent('Autopilot Business SME');
    await userEvent.click(within(group).getByRole('radio', { name: 'I answer' }));
    await waitFor(() => expect(api.called('setControl')[1].args).toEqual(['human']));
  });

  it('can be switched with the arrow keys', async () => {
    const api = new FakeStandupApi().with(makeView());
    await shown(api);
    const human = screen.getByRole('radio', { name: 'I answer' });
    human.focus();
    fireEvent.keyDown(human, { key: 'ArrowRight' });
    await waitFor(() => expect(api.called('setControl')[0].args).toEqual(['autopilot']));
  });

  it('says it will answer shortly while the autopilot is on, and a person answering first still can', async () => {
    const q = question();
    await shown(new FakeStandupApi().with(makeView({ control_mode: 'autopilot', status: 'waiting_for_sme', open_questions: [q] })));
    expect(screen.getByText(/The autopilot will answer shortly/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes, persist them' })).toBeEnabled();
  });

  it('interrupts or redirects the meeting with a message to the team', async () => {
    const api = new FakeStandupApi().with(makeView());
    await shown(api);
    await userEvent.type(screen.getByLabelText('Interrupt or redirect'), 'Please keep it simple{enter}');
    await waitFor(() => expect(api.called('direct')[0].args).toEqual(['kickoff', 'Please keep it simple']));
    expect(await screen.findByText('The team heard you.')).toBeInTheDocument();
  });
});

describe('decisions, actions, risks and documents', () => {
  it('lists decisions with the settled ones before the rejected ones, and who proposed and settled them', async () => {
    const decision = (id: string, status: 'proposed' | 'accepted' | 'rejected' | 'deferred', extra = {}) => ({
      decision_id: id, meeting_id: 'kickoff', title: `Decision ${id}`, context: '', alternatives: ['a', 'b'], selected_option: null, status, decided_by: null, proposed_by: 'dev-1', reason: '', timestamp: null, ...extra,
    });
    const decisions = [decision('r', 'rejected', { reason: 'out of scope', decided_by: 'sme' }), decision('a', 'accepted', { selected_option: 'a', decided_by: 'sme' }), decision('d', 'deferred'), decision('p', 'proposed')];
    await shown(new FakeStandupApi().with(makeView({ decisions })));
    const items = screen.getAllByTestId('decision');
    expect(items.map((i) => i.getAttribute('data-status'))).toEqual(['proposed', 'accepted', 'deferred', 'rejected']);
    expect(within(items[1]).getByText('a', { selector: 'strong' })).toBeInTheDocument();
    expect(within(items[1]).getByText(/Proposed by Developer 01 · settled by Business SME/)).toBeInTheDocument();
    expect(within(items[3]).getByText('out of scope')).toBeInTheDocument();
  });

  it('says so when there is nothing yet', async () => {
    await shown(new FakeStandupApi().with(makeView()));
    expect(screen.getByText('No decision has been proposed yet.')).toBeInTheDocument();
    expect(screen.getByText('No action items yet.')).toBeInTheDocument();
    expect(screen.getByText('No document is under review.')).toBeInTheDocument();
    expect(screen.getByText('Nothing is waiting for the Business SME.')).toBeInTheDocument();
    expect(screen.queryByTestId('risk-panel')).not.toBeInTheDocument();
  });

  it('shows action items with their owners and state, risks and dependencies', async () => {
    const action_items = [
      { action_item_id: 'a1', meeting_id: 'kickoff', owner_id: 'dev-3', description: 'Write the timer plugin', status: 'in_progress' as const, due_reference: 'sprint 1', created_at: null, completed_at: null },
      { action_item_id: 'a2', meeting_id: 'kickoff', owner_id: 'gone', description: 'Old task', status: 'done' as const, due_reference: null, created_at: null, completed_at: null },
    ];
    const risks = [{ risk_id: 'r1', text: 'An alert could talk over the user.', severity: 'high', raised_by: 'dev-5' }];
    const dependencies = [{ dependency_id: 'd1', text: 'Needs the speaking state', from_id: 'dev-3', to_id: 'dev-6', identified_by: 'dev-5' }];
    await shown(new FakeStandupApi().with(makeView({ action_items, risks, dependencies })));
    const items = screen.getAllByTestId('action-item');
    expect(items[0]).toHaveTextContent('Owner: Developer 03 · due sprint 1');
    expect(items[0]).toHaveTextContent('In progress');
    expect(items[1]).toHaveTextContent('Owner: gone'); // someone who left: the id, not a crash
    expect(screen.getByTestId('risk')).toHaveTextContent('Risk · high');
    expect(screen.getByTestId('dependency')).toHaveTextContent('Developer 03 → Developer 06');
  });

  it('shows documents under review and approves the documents through the same command the Control Plane uses', async () => {
    const approvals = [{ request_id: 'req-1', subject: 'Accept the PRD', requested_by: 'sm', open: true, approved: null, comment: '', extra: { kind: 'documents', context: 'Read the PRD first.' } }];
    const reviews = [{ document_path: 'PRD.md', meeting_id: 'kickoff', reviewer_id: 'sme', status: 'in_review' as const, comments: [], reviewed_at: null }];
    const api = new FakeStandupApi().with(makeView({ status: 'awaiting_approval', reviews, approvals_open: approvals }));
    const { repository } = await shown(api);
    expect(screen.getByTestId('document-review')).toHaveTextContent('PRD.md');
    expect(screen.getByTestId('document-review')).toHaveTextContent('In review');
    expect(screen.getByText('Read the PRD first.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(repository.commandsOfType('prd.accept')).toHaveLength(1));
    expect(repository.commandsOfType('prd.accept')[0]).toMatchObject({ artifactId: 'art-prd' });
  });

  it('asks for changes with a reason, and approves other decisions by their request id', async () => {
    const approvals = [
      { request_id: 'req-docs', subject: 'Accept the PRD', requested_by: 'sm', open: true, approved: null, comment: '', extra: { kind: 'documents' } },
      { request_id: 'req-dep', subject: 'Add a dependency?', requested_by: 'sm', open: true, approved: null, comment: '', extra: { kind: 'approval' } },
    ];
    const { repository } = await shown(new FakeStandupApi().with(makeView({ status: 'awaiting_approval', approvals_open: approvals })));
    const [docs, dep] = screen.getAllByTestId('approval');
    expect(within(docs).getByRole('button', { name: 'Request changes' })).toBeDisabled(); // a reason is needed
    await userEvent.type(within(docs).getByLabelText('Reason, if you ask for changes'), 'List the refusals');
    await userEvent.click(within(docs).getByRole('button', { name: 'Request changes' }));
    await userEvent.click(within(dep).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(repository.commandsOfType('sme.directive.submit')).toHaveLength(2));
    expect(repository.commandsOfType('sme.directive.submit').map((c) => ({ q: (c as { questionId?: string }).questionId, d: (c as { directive: string }).directive }))).toEqual([
      { q: 'req-docs', d: 'Decline: List the refusals' }, { q: 'req-dep', d: 'Approve' },
    ]);
  });

  it('shows the summary when there is one', async () => {
    await shown(new FakeStandupApi().with(makeView({ summary: 'Timers live in a plugin.' })));
    expect(screen.getByTestId('summary')).toHaveTextContent('Timers live in a plugin.');
  });
});

describe('time', () => {
  it('counts the meeting clock on, and stops it while paused', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    try {
      const api = new FakeStandupApi().with(makeView({ elapsed_seconds: 125, remaining_seconds: 3475 }));
      renderStandup(api);
      await vi.waitFor(() => expect(screen.getByTestId('elapsed')).toBeInTheDocument());
      expect(screen.getByTestId('elapsed')).toHaveTextContent('00:02:05');
      expect(screen.getByTestId('remaining')).toHaveTextContent('00:57:55');
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(screen.getByTestId('elapsed')).toHaveTextContent('00:02:10');
      expect(screen.getByTestId('remaining')).toHaveTextContent('00:57:50');
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows a paused meeting as paused with a standing clock', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    try {
      renderStandup(new FakeStandupApi().with(makeView({ paused: true, status: 'paused', elapsed_seconds: 60 })));
      await vi.waitFor(() => expect(screen.getByTestId('elapsed')).toBeInTheDocument());
      await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
      expect(screen.getByTestId('elapsed')).toHaveTextContent('00:01:00');
      expect(within(screen.getByTestId('meeting-timer')).getByText('Paused')).toBeInTheDocument();
      expect(screen.getByTestId('meeting-status')).toHaveTextContent('Paused');
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows a finished meeting with its final time and no live indicator', async () => {
    await shown(new FakeStandupApi().with(makeView({ status: 'completed', elapsed_seconds: 3600, remaining_seconds: 0 })));
    expect(screen.getByTestId('elapsed')).toHaveTextContent('01:00:00');
    expect(screen.getByTestId('meeting-status')).toHaveTextContent('Finished');
    expect(screen.queryByTestId('stream-state')).not.toBeInTheDocument();
  });
});

describe('staying in step with a live meeting', () => {
  it('follows the stream from the last event it has, and refreshes the view when something is said', async () => {
    const api = new FakeStandupApi().with(makeView({ last_sequence: 2 }), [wire(1, 'meeting_created'), wire(2, 'meeting_started')]);
    await shown(api);
    await waitFor(() => expect(api.streamOpened).toEqual([{ meetingId: 'kickoff', after: 2 }]));
    expect(screen.getByTestId('stream-state')).toHaveTextContent('Live');
    api.views.set('kickoff', makeView({ last_sequence: 3, recent: [entry(3, 'statement', 'A new line.')] }));
    act(() => api.push(wire(3, 'statement', { text: 'A new line.' })));
    expect(await screen.findByText('A new line.')).toBeInTheDocument();
    expect(screen.getByText('3 events recorded')).toBeInTheDocument();
  });

  it('stores an event once however many times it arrives, and does not ask for the view for each copy', async () => {
    const api = new FakeStandupApi().with(makeView({ last_sequence: 2 }), [wire(1, 'meeting_created'), wire(2, 'meeting_started')]);
    await shown(api);
    await waitFor(() => expect(api.streamsOpen).toBe(1));
    const views = () => api.called('getMeeting').length;
    api.views.set('kickoff', makeView({ last_sequence: 3, recent: [entry(3, 'statement', 'Once.')] }));
    const before = views();
    act(() => { api.push(wire(3, 'statement')); api.push(wire(3, 'statement')); api.push(wire(3, 'statement')); });
    await screen.findByText('Once.');
    expect(views() - before).toBe(1);
    expect(screen.getByText('3 events recorded')).toBeInTheDocument();
    expect(screen.getAllByTestId('timeline-entry')).toHaveLength(1);
  });

  it('says the connection dropped, and on reconnecting fetches what it missed from the last event it has', async () => {
    const api = new FakeStandupApi().with(makeView({ last_sequence: 2 }), [wire(1, 'meeting_created'), wire(2, 'meeting_started')]);
    await shown(api);
    await waitFor(() => expect(api.streamsOpen).toBe(1));
    act(() => api.state('reconnecting'));
    expect(await screen.findByText(/The connection to the meeting was lost/)).toBeInTheDocument();
    expect(screen.getByTestId('stream-state')).toHaveTextContent('reconnecting');
    api.eventsByMeeting.set('kickoff', [wire(1, 'meeting_created'), wire(2, 'meeting_started'), wire(3, 'statement'), wire(4, 'statement')]);
    api.views.set('kickoff', makeView({ last_sequence: 4, recent: [entry(4, 'statement', 'Said during the drop.')] }));
    const catchUps = api.called('getEvents').length;
    act(() => api.state('connected'));
    await waitFor(() => expect(api.called('getEvents').length).toBeGreaterThan(catchUps));
    expect(api.called('getEvents').at(-1)!.args).toEqual(['kickoff', 2]);
    expect(await screen.findByText('Said during the drop.')).toBeInTheDocument();
    expect(screen.queryByText(/The connection to the meeting was lost/)).not.toBeInTheDocument();
  });

  it('does not stream a meeting that is over, nor an earlier project record', async () => {
    const api = new FakeStandupApi().with(makeView({ status: 'completed' }), [wire(1, 'meeting_created')]);
    await shown(api);
    expect(api.streamOpened).toEqual([]);
  });

  it('stops streaming when the screen closes', async () => {
    const api = new FakeStandupApi().with(makeView(), [wire(1, 'meeting_created')]);
    const { unmount } = await shown(api);
    await waitFor(() => expect(api.streamsOpen).toBe(1));
    unmount();
    expect(api.streamsOpen).toBe(0);
  });

  it('ignores an older answer that arrives after a newer one', async () => {
    const api = new FakeStandupApi().with(makeView({ last_sequence: 2 }), [wire(1, 'meeting_created'), wire(2, 'meeting_started')]);
    await shown(api);
    await waitFor(() => expect(api.streamsOpen).toBe(1));
    api.views.set('kickoff', makeView({ last_sequence: 5, title: 'Newest', recent: [entry(5, 'statement', 'five')] }));
    act(() => api.push(wire(5, 'statement')));
    await screen.findByText('Newest');
    api.views.set('kickoff', makeView({ last_sequence: 3, title: 'Stale', recent: [] }));
    await act(async () => { await new Promise((r) => setTimeout(r, 300)); api.push(wire(3, 'statement')); await new Promise((r) => setTimeout(r, 300)); });
    expect(screen.queryByText('Stale')).not.toBeInTheDocument();
    expect(screen.getByText('Newest')).toBeInTheDocument();
  });
});

describe('replaying a meeting', () => {
  const events = [1, 2, 3, 4, 5, 6].map((n) => wire(n, n === 3 ? 'decision_proposed' : n === 5 ? 'clarification_requested' : 'statement', {}, { elapsed_seconds: n }));
  const apiWithReplay = () => {
    const api = new FakeStandupApi().with(makeView({ status: 'completed', last_sequence: 6 }), events);
    api.viewAt = (id, at) => makeView({ status: at >= 6 ? 'completed' : 'active', last_sequence: at, elapsed_seconds: at, recent: [entry(at, 'statement', `line ${at}`)] });
    return api;
  };

  it('starts at the beginning, shows the state at each point and steps through it', async () => {
    const api = apiWithReplay();
    await shown(api);
    await userEvent.click(screen.getByRole('button', { name: 'Replay this meeting' }));
    expect(await screen.findByTestId('replay-controls')).toBeInTheDocument();
    expect(screen.getByTestId('stream-state')).toHaveTextContent('Replay');
    expect(await screen.findByText('line 1')).toBeInTheDocument();
    expect(screen.getByTestId('replay-position')).toHaveTextContent('event 1 of 6');
    expect(screen.getByRole('button', { name: 'Previous event' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Next event' }));
    expect(await screen.findByText('line 2')).toBeInTheDocument();
    expect(api.called('getMeeting').some((c) => (c.args[1] as { at?: number }).at === 2)).toBe(true);
    fireEvent.change(screen.getByRole('slider', { name: 'Replay position' }), { target: { value: '5' } });
    expect(await screen.findByText('line 5')).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Replay position' })).toHaveAttribute('aria-valuetext', 'event 5 of 6');
  });

  it('jumps to the decisions, the questions and the interventions', async () => {
    await shown(apiWithReplay());
    await userEvent.click(screen.getByRole('button', { name: 'Replay this meeting' }));
    await screen.findByTestId('replay-controls');
    await userEvent.click(screen.getByRole('button', { name: 'Next decision' }));
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent('event 3 of 6'));
    await userEvent.click(screen.getByRole('button', { name: 'Next question' }));
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent('event 5 of 6'));
    await userEvent.click(screen.getByRole('button', { name: 'Previous decision' }));
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent('event 3 of 6'));
    await userEvent.click(screen.getByRole('button', { name: 'Next intervention' })); // there is none: nothing moves
    expect(screen.getByTestId('replay-position')).toHaveTextContent('event 3 of 6');
  });

  it('plays on its own at the chosen speed, pauses, and stops at the end', async () => {
    const api = apiWithReplay();
    await shown(api);
    await userEvent.click(screen.getByRole('button', { name: 'Replay this meeting' }));
    await screen.findByTestId('replay-controls');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Playback speed' }), '8');
    await userEvent.click(screen.getByRole('button', { name: 'Play replay' }));
    expect(screen.getByRole('button', { name: 'Pause replay' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('replay-position')).toHaveTextContent('event 6 of 6'), { timeout: 4000 });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Play replay' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Next event' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Restart replay' }));
    expect(screen.getByTestId('replay-position')).toHaveTextContent('event 1 of 6');
  });

  it('cannot be used to answer or interrupt, and goes back to live', async () => {
    const q = question();
    const api = apiWithReplay();
    api.viewAt = (id, at) => makeView({ last_sequence: at, status: 'active', open_questions: [q], recent: [entry(at, 'statement', `line ${at}`)] });
    await shown(api);
    await userEvent.click(screen.getByRole('button', { name: 'Replay this meeting' }));
    await screen.findByTestId('replay-controls');
    await screen.findByTestId('question-card');
    expect(screen.getByRole('button', { name: 'Yes, persist them' })).toBeDisabled();
    expect(screen.getByLabelText('Interrupt or redirect')).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Back to live' }));
    expect(screen.queryByTestId('replay-controls')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Replay this meeting' })).toBeInTheDocument();
  });

  it('says so when the replay cannot be loaded', async () => {
    const api = apiWithReplay();
    api.viewAt = () => { throw new Error('the record is damaged'); };
    await shown(api);
    await userEvent.click(screen.getByRole('button', { name: 'Replay this meeting' }));
    expect(await screen.findByText('the record is damaged')).toBeInTheDocument();
  });
});

describe('before there is anything to show', () => {
  it('explains that meetings need a backend when there is none', () => {
    renderStandup(undefined);
    expect(screen.getByText(/Meetings need a backend that records them/)).toBeInTheDocument();
  });

  it('says there is no meeting yet, and what will appear', async () => {
    renderStandup(new FakeStandupApi());
    expect(await screen.findByTestId('no-meeting')).toHaveTextContent('appear here as the team holds them');
    expect(screen.getByText(/No meeting has started yet/)).toBeInTheDocument();
  });

  it('shows a loading state, then the meeting', async () => {
    const api = new FakeStandupApi().with(makeView());
    renderStandup(api);
    expect(screen.getByText('Loading meetings…')).toBeInTheDocument();
    await screen.findByTestId('meeting-header');
    expect(screen.queryByText('Loading meetings…')).not.toBeInTheDocument();
  });

  it('shows an error when the list cannot be loaded, and loads it on retry', async () => {
    const api = new FakeStandupApi().with(makeView());
    api.failList = 'The backend could not be reached';
    renderStandup(api);
    expect(await screen.findByText(/The meeting list could not be loaded: The backend could not be reached/)).toBeInTheDocument();
    api.failList = null;
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByTestId('meeting-header');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows an error when one meeting cannot be loaded, and loads it on retry', async () => {
    const api = new FakeStandupApi().with(makeView());
    api.failMeeting = 'The record is damaged';
    renderStandup(api);
    expect(await screen.findByText(/This meeting could not be loaded: The record is damaged/)).toBeInTheDocument();
    api.failMeeting = null;
    const retries = screen.getAllByRole('button', { name: 'Retry' });
    await userEvent.click(retries[retries.length - 1]);
    await screen.findByTestId('meeting-header');
  });

  it('opens a meeting that is waiting for the Business SME before the others', async () => {
    const waiting = makeView({ meeting_id: 'w', title: 'Waiting meeting', status: 'waiting_for_sme', open_questions: [question({ meeting_id: 'w' })] });
    const api = new FakeStandupApi().with(makeView({ meeting_id: 'first', title: 'First meeting', status: 'completed' })).with(waiting).with(makeView({ meeting_id: 'last', title: 'Last meeting', status: 'completed' }));
    api.rows = api.rows.map((r) => (r.meeting_id === 'w' ? row({ ...r, open_questions: 1, status: 'waiting_for_sme' }) : r));
    renderStandup(api);
    expect(await screen.findByRole('heading', { level: 1, name: 'Waiting meeting' })).toBeInTheDocument();
    expect(screen.getByText('1 waiting for you')).toBeInTheDocument();
  });

  it('opens the meeting asked for in the address, not the default one', async () => {
    const waiting = makeView({ meeting_id: 'w', title: 'Waiting meeting', status: 'waiting_for_sme', open_questions: [question({ meeting_id: 'w' })] });
    const api = new FakeStandupApi().with(makeView({ meeting_id: 'asked', title: 'Asked for', status: 'completed' })).with(waiting);
    api.rows = api.rows.map((r) => (r.meeting_id === 'w' ? row({ ...r, open_questions: 1, status: 'waiting_for_sme' }) : r));
    renderStandup(api, <StandupView initialMeetingId="asked" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Asked for' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 1, name: 'Waiting meeting' })).not.toBeInTheDocument();
  });

  it('falls back to the default when the meeting asked for does not exist', async () => {
    const api = new FakeStandupApi().with(makeView({ title: 'Only meeting' }));
    renderStandup(api, <StandupView initialMeetingId="long-gone" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Only meeting' })).toBeInTheDocument();
  });

  it('can look at an earlier project record, read only', async () => {
    const api = new FakeStandupApi().with(makeView({ status: 'completed' }));
    api.records = ['run-0', 'run-1'];
    await shown(api);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Project record' }), 'run-0');
    await waitFor(() => expect(api.called('listMeetings').some((c) => c.args[0] === 'run-0')).toBe(true));
    await waitFor(() => expect(api.called('getMeeting').some((c) => (c.args[1] as { record?: string }).record === 'run-0')).toBe(true));
    expect(screen.getByRole('radio', { name: 'I answer' })).toBeDisabled();
  });
});

describe('using it without a mouse, or with a screen reader', () => {
  it('names every control, and every list and region', async () => {
    const q = question();
    await shown(new FakeStandupApi().with(makeView({ status: 'waiting_for_sme', open_questions: [q], decisions: [] })));
    for (const button of screen.getAllByRole('button')) expect(button).toHaveAccessibleName();
    for (const field of screen.getAllByRole('textbox')) expect(field).toHaveAccessibleName();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Meetings' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Participants' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Decisions' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Questions for the Business SME' })).toBeInTheDocument();
    expect(screen.getByRole('timer')).toBeInTheDocument();
    expect(screen.getAllByRole('list').length).toBeGreaterThan(0);
  });

  it('reads out a connection problem and does not rely on colour alone for the state of a person', async () => {
    const api = new FakeStandupApi().with(makeView({ participants: [person('a', 'Ada', 'developer', { status: 'blocked' })] }), [wire(1, 'meeting_created')]);
    await shown(api);
    await waitFor(() => expect(api.streamsOpen).toBe(1));
    act(() => api.state('reconnecting'));
    expect((await screen.findAllByRole('alert')).length).toBeGreaterThan(0);
    expect(screen.getByText('Ada').closest('li')).toHaveAccessibleName(/Blocked/);
    expect(screen.getByText('Blocked')).toBeInTheDocument();
  });

  it('can be driven from the keyboard: the meetings, the answer field and the replay button are all reachable with Tab and Enter', async () => {
    const q = question({ options: [] });
    const api = new FakeStandupApi().with(makeView({ status: 'waiting_for_sme', open_questions: [q] }), [wire(1, 'meeting_created')]);
    api.rows = [row({ open_questions: 1, status: 'waiting_for_sme' })];
    await shown(api);
    const first = within(screen.getByTestId('meeting-picker')).getByRole('button', { name: /Discovery: Jarvis/ });
    first.focus();
    await userEvent.keyboard('{Enter}');
    const answer = screen.getByLabelText('Your answer');
    answer.focus();
    await userEvent.keyboard('Yes{Enter}');
    await waitFor(() => expect(api.called('answer')).toHaveLength(1));
    screen.getByRole('button', { name: 'Replay this meeting' }).focus();
    await userEvent.keyboard('{Enter}');
    expect(await screen.findByTestId('replay-controls')).toBeInTheDocument();
  });
});
