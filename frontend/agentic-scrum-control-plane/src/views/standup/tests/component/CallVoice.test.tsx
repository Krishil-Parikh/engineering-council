import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CallView } from '../../call/CallView';
import { LiveTranscript, transcriptLines } from '../../call/LiveTranscript';
import { voiceFor } from '../../call/useVoice';
import { entry, makeView, wire } from '../helpers';

const actions = { disabled: false, autopilot: false, onAnswer: () => undefined, onDecide: () => undefined };
const silent = { supported: false, enabled: false, setEnabled: () => undefined, say: vi.fn(() => () => undefined), stop: vi.fn() };

type Said = { text: string; who: string | null | undefined; end: () => void; start?: () => void };
const said: Said[] = [];
const speaking = {
  supported: true, enabled: true, setEnabled: () => undefined, stop: vi.fn(),
  say: vi.fn((text: string, who: string | null | undefined, _rate: number, h: { onStart?: () => void; onEnd: () => void }) => { said.push({ text, who, end: h.onEnd, start: h.onStart }); return () => undefined; }),
};

function call(view = makeView(), extra: Partial<Parameters<typeof CallView>[0]> = {}) {
  return <CallView view={view} events={[]} transcriptOpen={false} replaying={false} playing speed={1} layout="grid" pinned={null} onPin={() => undefined} actions={actions} voice={silent} resetKey="k" selectedId={null} onSelectPerson={() => undefined} {...extra} />;
}

beforeEach(() => { vi.useFakeTimers(); said.length = 0; speaking.say.mockClear(); });
afterEach(() => vi.useRealTimers());

describe('the voice', () => {
  it('says each piece in the voice of the person who speaks, and the subtitle moves on when the voice has finished it', () => {
    const { rerender } = render(call(makeView({ recent: [entry(4, 'statement', 'Keep one process.')], last_sequence: 4 }), { voice: speaking }));
    rerender(call(makeView({ recent: [entry(4, 'statement', 'Keep one process.'), entry(5, 'challenge', 'We do not know the traffic. Measure first.', { actor_id: 'dev-3' })], last_sequence: 5 }), { voice: speaking }));
    expect(said.map((s) => [s.text, s.who])).toEqual([['We do not know the traffic.', 'dev-3']]);
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('We do not know the traffic.');
    act(() => { said[0].start?.(); vi.advanceTimersByTime(20_000); }); // however long the voice takes, the subtitle stays with it
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('We do not know the traffic.');
    act(() => said[0].end());
    expect(said.map((s) => s.text)).toEqual(['We do not know the traffic.', 'Measure first.']);
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('Measure first.');
    act(() => { said[1].start?.(); said[1].end(); vi.advanceTimersByTime(500); });
    expect(screen.queryByTestId('speech-bubble')).not.toBeInTheDocument(); // the last piece has been said
  });

  it('goes on by the clock when the browser never speaks', () => {
    const { rerender } = render(call(makeView({ recent: [entry(4, 'statement', 'Old.')], last_sequence: 4 }), { voice: speaking }));
    rerender(call(makeView({ recent: [entry(4, 'statement', 'Old.'), entry(5, 'statement', 'First piece. Second piece.')], last_sequence: 5 }), { voice: speaking }));
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('First piece.');
    act(() => { vi.advanceTimersByTime(2500 + 1500); });
    expect(screen.getByTestId('subtitle-text')).toHaveTextContent('Second piece.');
  });

  it('offers to turn the voice on, and does not when it is on or the browser cannot speak', () => {
    const setEnabled = vi.fn();
    const { rerender } = render(call(makeView(), { voice: { ...silent, supported: true, setEnabled } }));
    fireEvent.click(screen.getByTestId('turn-on-voice'));
    expect(setEnabled).toHaveBeenCalledWith(true);
    rerender(call(makeView(), { voice: silent }));
    expect(screen.queryByTestId('turn-on-voice')).not.toBeInTheDocument();
    rerender(call(makeView(), { voice: speaking }));
    expect(screen.queryByTestId('turn-on-voice')).not.toBeInTheDocument();
  });

  it('gives each person a voice of their own, always the same one', () => {
    const voices = Array.from({ length: 6 }, (_, i) => ({ name: `v${i}`, lang: 'en-GB' } as SpeechSynthesisVoice));
    expect(voiceFor('dev-1', voices)).toEqual(voiceFor('dev-1', voices));
    const looks = ['dev-1', 'dev-2', 'dev-3', 'dev-4', 'sme', 'sm'].map((id) => voiceFor(id, voices));
    expect(new Set(looks.map((l) => `${l.voice?.name}|${l.pitch.toFixed(2)}|${l.pace.toFixed(2)}`)).size).toBeGreaterThanOrEqual(5);
    expect(looks.every((l) => l.pitch >= 0.8 && l.pitch <= 1.25 && l.pace >= 0.9 && l.pace <= 1.12)).toBe(true);
    expect(voiceFor('dev-1', [])).toMatchObject({ voice: null }); // no voices to choose from: the browser's own
    const mixed = [{ name: 'fr', lang: 'fr-FR' }, { name: 'en', lang: 'en-US' }] as SpeechSynthesisVoice[];
    expect(voiceFor('anyone', mixed).voice?.name).toBe('en');
  });
});

describe('the live transcript', () => {
  const events = [
    wire(1, 'meeting_started'), wire(2, 'statement', { text: 'Keep one process.' }, { actor_id: 'dev-1', elapsed_seconds: 65 }),
    wire(3, 'challenge', { text: 'We do not know the traffic. Measure first.' }, { actor_id: 'dev-3', elapsed_seconds: 75 }), wire(4, 'clarification_answered', { question_id: 'q', answer: 'Memory only.' }, { actor_id: 'sme', elapsed_seconds: 90 }),
    wire(5, 'decision_accepted', { decision_id: 'd' }),
  ];

  it('lists what was said with who said it and when, and leaves out what was not said', () => {
    const lines = transcriptLines(events, makeView().participants);
    expect(lines.map((l) => [l.sequence, l.name, l.kind, l.text])).toEqual([
      [2, 'Developer 01', '', 'Keep one process.'], [3, 'Developer 03', 'challenge', 'We do not know the traffic. Measure first.'], [4, 'Business SME', 'answer', 'Memory only.'],
    ]);
  });

  it('shows the sentence being said now inside the line that is being said', () => {
    const active = { entry: entry(3, 'challenge', 'We do not know the traffic. Measure first.'), pieces: ['We do not know the traffic.', 'Measure first.'], index: 0, animating: true };
    render(<LiveTranscript events={events} participants={makeView().participants} active={active} replaying={false} />);
    expect(screen.getAllByTestId('transcript-line')).toHaveLength(3);
    const now = screen.getAllByTestId('transcript-line').find((l) => l.getAttribute('data-now') === 'true')!;
    expect(now).toHaveTextContent('Developer 03');
    expect(within(now).getByTestId('transcript-now')).toHaveTextContent('We do not know the traffic.');
  });

  it('lets a replay jump to a line, and a live meeting not', () => {
    const onSeek = vi.fn();
    const { rerender } = render(<LiveTranscript events={events} participants={makeView().participants} active={null} replaying onSeek={onSeek} />);
    fireEvent.click(screen.getByRole('button', { name: /Go to Developer 03 at 00:01:15/ }));
    expect(onSeek).toHaveBeenCalledWith(3);
    rerender(<LiveTranscript events={events} participants={makeView().participants} active={null} replaying={false} onSeek={onSeek} />);
    expect(screen.queryByRole('button', { name: /Go to/ })).not.toBeInTheDocument();
  });

  it('sits beside the call when it is open, and says so when nothing has been said', () => {
    const { rerender } = render(call(makeView(), { events: [], transcriptOpen: true }));
    expect(screen.getByTestId('live-transcript')).toHaveTextContent('Nothing has been said yet.');
    rerender(call(makeView(), { events, transcriptOpen: true }));
    expect(screen.getAllByTestId('transcript-line')).toHaveLength(3);
    rerender(call(makeView(), { events, transcriptOpen: false }));
    expect(screen.queryByTestId('live-transcript')).not.toBeInTheDocument();
  });
});
