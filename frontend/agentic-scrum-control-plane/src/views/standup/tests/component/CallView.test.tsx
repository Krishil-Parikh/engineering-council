import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CallView } from '../../call/CallView';
import { HighlightsBar } from '../../call/HighlightsBar';
import { NeedsYouLine } from '../../call/NeedsYouLine';
import { entry, makeView, person } from '../helpers';

const voice = { supported: false, enabled: false, setEnabled: () => undefined, say: vi.fn(() => () => undefined), stop: vi.fn() };
const actions = { disabled: false, autopilot: false, onAnswer: () => undefined, onDecide: () => undefined };

function call(view = makeView(), extra: Partial<Parameters<typeof CallView>[0]> = {}) {
  return <CallView view={view} events={[]} transcriptOpen={false} replaying={false} playing speed={1} layout="grid" pinned={null} onPin={() => undefined} actions={actions} voice={voice} resetKey="k" selectedId={null} onSelectPerson={() => undefined} {...extra} />;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('the call', () => {
  it('shows everyone at their desk, in a steady order, with the Business SME first', () => {
    render(call());
    const tiles = screen.getAllByTestId('call-tile');
    expect(tiles).toHaveLength(8);
    expect(tiles[0]).toHaveAccessibleName(/Business SME/);
    expect(tiles[1]).toHaveAccessibleName(/Scrum Master/);
  });

  it('shows the line that is already there whole, and says each new line a piece at a time, one person at a time', () => {
    const first = makeView({ recent: [entry(4, 'statement', 'Keep one process.')], last_sequence: 4 });
    const { rerender } = render(call(first));
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('Keep one process.');
    expect(screen.queryByTestId('speech-bubble')).not.toBeInTheDocument(); // what was said before this screen opened is not played again

    const next = makeView({
      recent: [
        entry(4, 'statement', 'Keep one process.'),
        entry(5, 'challenge', 'We do not know the traffic. Measure first.', { actor_id: 'dev-3', actor_name: 'Developer 03' }),
        entry(6, 'statement', 'Agreed.', { actor_id: 'dev-2', actor_name: 'Developer 02' }),
      ],
      last_sequence: 6,
    });
    rerender(call(next));
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('We do not know the traffic.');
    const talking = screen.getAllByTestId('call-tile').filter((t) => t.getAttribute('data-speaking') === 'true');
    expect(talking).toHaveLength(1);
    expect(talking[0]).toHaveAccessibleName(/Developer 03/);
    expect(screen.getByTestId('speech-bubble')).toHaveTextContent('Measure first.');
    expect(screen.getByText('+1 next')).toBeInTheDocument(); // Developer 02 waits for their turn
    act(() => { vi.advanceTimersByTime(2300); });
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('Measure first.');
    act(() => { vi.advanceTimersByTime(4000); });
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('Agreed.');
    act(() => { vi.advanceTimersByTime(4000); });
    expect(screen.queryByTestId('speech-bubble')).not.toBeInTheDocument(); // nobody is talking now
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('Agreed.'); // the last line stays until the next one
  });

  it('does not fall behind: a burst of lines keeps only the latest few', () => {
    const lines = (n: number) => Array.from({ length: n }, (_, i) => entry(10 + i, 'statement', `line ${i}.`, { actor_id: 'dev-1' }));
    const { rerender } = render(call(makeView({ recent: lines(1), last_sequence: 10 })));
    rerender(call(makeView({ recent: lines(8), last_sequence: 17 })));
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('line 7.');
  });

  it('stands still while paused', () => {
    const base = makeView({ recent: [entry(4, 'statement', 'First.')], last_sequence: 4 });
    const { rerender } = render(call(base, { playing: false }));
    rerender(call(makeView({ recent: [entry(4, 'statement', 'First.'), entry(5, 'statement', 'Second one. And a third.')], last_sequence: 5 }), { playing: false }));
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('First.');
  });

  it('shows the person who is blocked, the one who needs the Business SME, and the shared screen with the question', () => {
    const view = makeView({
      participants: [person('sme', 'Business SME', 'business_sme', { status: 'needs_sme', needs_sme: true }), person('a', 'Ada', 'developer', { status: 'blocked' })],
      open_questions: [{ question_id: 'q', meeting_id: 'k', asked_by: 'a', target: 'business_sme', text: 'Which way?', status: 'open', answer: null, answered_by: null, options: ['A', 'B'], recommended: 'A', asked_at: null, answered_at: null }],
    });
    render(call(view));
    expect(screen.getByTestId('call-stage')).toHaveAttribute('data-shown', 'question');
    expect(within(screen.getByTestId('call-stage')).getByText('Which way?')).toBeInTheDocument();
    expect(screen.getAllByTestId('call-tile').map((t) => t.getAttribute('data-state'))).toEqual(['needs_sme', 'blocked']);
  });

  it('lets the person pin what is on the shared screen', () => {
    const onPin = vi.fn();
    const decision = { decision_id: 'd', meeting_id: 'k', title: 'Alerts wait', context: '', alternatives: [], selected_option: 'wait', status: 'accepted' as const, decided_by: null, proposed_by: null, reason: '', timestamp: null };
    render(call(makeView({ decisions: [decision] }), { onPin }));
    fireEvent.click(screen.getByRole('button', { name: 'Next on the shared screen' }));
    expect(onPin).toHaveBeenCalledWith('decision');
  });
});

describe('the red line and the highlights', () => {
  it('says who needs the Business SME, for what and for how long, and goes there on a click', () => {
    const onGo = vi.fn();
    render(<NeedsYouLine items={[{ meetingId: 'm1', title: 'Sprint 1 planning', text: 'Is a limit of 10 right?', count: 1, waitedSeconds: 125 }, { meetingId: 'm2', title: 'Decisions', text: '', count: 2, waitedSeconds: null }]} onGo={onGo} />);
    const line = screen.getByTestId('needs-you');
    expect(line).toHaveTextContent('Sprint 1 planning needs you · Is a limit of 10 right? · 2m');
    expect(line).toHaveTextContent('+2');
    fireEvent.click(line);
    expect(onGo).toHaveBeenCalledWith('m1');
  });

  it('is not there when nothing is waiting', () => {
    render(<NeedsYouLine items={[]} onGo={() => undefined} />);
    expect(screen.queryByTestId('needs-you')).not.toBeInTheDocument();
  });

  it('jumps to a highlight when it is clicked, and marks the one it is at', () => {
    const onSeek = vi.fn();
    render(<HighlightsBar highlights={[{ sequence: 4, kind: 'question', label: 'Question: x' }, { sequence: 9, kind: 'decision', label: 'Decided: y' }]} position={9} onSeek={onSeek} />);
    fireEvent.click(screen.getByRole('button', { name: 'Question: x' }));
    expect(onSeek).toHaveBeenCalledWith(4);
    expect(screen.getByRole('button', { name: 'Decided: y' })).toHaveAttribute('aria-current', 'true');
  });
});
