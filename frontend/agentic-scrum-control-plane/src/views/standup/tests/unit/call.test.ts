import { describe, expect, it } from 'vitest';
import { busiest, computeHighlights, lookFor, pieceStarts, recapMarkdown, speechMs, splitPieces, stageChoices, stageFor, waitedLabel, waitedSeconds } from '../../call/script';
import { tileOrder } from '../../call/CallView';
import { developers, entry, makeView, person, wire } from '../helpers';

describe('a line is shown a piece at a time', () => {
  it('cuts into sentences, and a long sentence at its commas', () => {
    expect(splitPieces('One. Two! Three?')).toEqual(['One.', 'Two!', 'Three?']);
    expect(splitPieces('  ')).toEqual([]);
    const long = 'The proposed service split is premature because we do not yet know the traffic profile, the team has not agreed on the data model, and nobody has costed the extra hosting.';
    const pieces = splitPieces(long);
    expect(pieces.length).toBeGreaterThan(1);
    expect(pieces.join(' ')).toBe(long);
    expect(pieces.every((p) => p.length <= 130)).toBe(true);
  });

  it('spreads the time over the pieces by their length, and never says a line in under a second and a half', () => {
    expect(speechMs('Hi', 1)).toBe(1400);
    expect(speechMs('word '.repeat(20), 2)).toBeLessThan(speechMs('word '.repeat(20), 1));
    expect(pieceStarts(['aaaa', 'bbbbbbbb'], 3000)).toEqual([0, 1000]);
    expect(pieceStarts([], 1000)).toEqual([]);
  });
});

describe('the shared screen', () => {
  it('shows what needs the Business SME first, then what the meeting has just been doing', () => {
    const q = { question_id: 'q', meeting_id: 'k', asked_by: 'dev-1', target: 'business_sme', text: 'Ok?', status: 'open' as const, answer: null, answered_by: null, options: [], recommended: null, asked_at: null, answered_at: null };
    expect(stageFor(makeView({ open_questions: [q] }))).toBe('question');
    expect(stageFor(makeView({ approvals_open: [{ request_id: 'r', subject: 'Accept', requested_by: null, open: true, approved: null, comment: '', extra: {} }] }))).toBe('documents');
    const decision = { decision_id: 'd', meeting_id: 'k', title: 'T', context: '', alternatives: [], selected_option: 'a', status: 'accepted' as const, decided_by: null, proposed_by: null, reason: '', timestamp: null };
    expect(stageFor(makeView({ decisions: [decision], recent: [entry(4, 'statement', 'hi'), entry(5, 'decision_accepted', 'Decision accepted: T')] }))).toBe('decision');
    expect(stageFor(makeView({ recent: [entry(5, 'statement', 'hi')] }))).toBe('now');
    expect(stageChoices(makeView())).toEqual(['now']);
    expect(stageChoices(makeView({ decisions: [decision] }))).toEqual(['now', 'decision']);
  });

  it('says how long a person has waited, and ignores a wait of weeks (a recording)', () => {
    const now = Date.parse('2026-03-02T10:00:00Z');
    expect(waitedSeconds('2026-03-02T09:57:00Z', now)).toBe(180);
    expect(waitedSeconds('2026-01-01T00:00:00Z', now)).toBeNull();
    expect(waitedSeconds(null, now)).toBeNull();
    expect(waitedLabel(45)).toBe('45s');
    expect(waitedLabel(180)).toBe('3m');
    expect(waitedLabel(3900)).toBe('1h 5m');
  });
});

describe('highlights, recap and looks', () => {
  const events = [
    wire(1, 'statement'), wire(2, 'clarification_requested', { text: 'Should timers survive a restart?' }), wire(3, 'decision_accepted', { selected_option: 'wait' }), wire(4, 'participant_blocked', { reason: 'needs the bus' }),
    wire(5, 'human_takeover'), wire(6, 'risk_raised', { text: 'alerts talk over the user' }),
  ];

  it('picks the moments worth jumping to, in order', () => {
    const h = computeHighlights(events);
    expect(h.map((x) => [x.sequence, x.kind])).toEqual([[2, 'question'], [3, 'decision'], [4, 'blocked'], [5, 'intervention'], [6, 'risk']]);
    expect(h[0].label).toBe('Question: Should timers survive a restart?');
    expect(h[1].label).toBe('Decided: wait');
  });

  it('writes the meeting as notes', () => {
    const view = makeView({
      summary: 'Memory only.', participants: [person('a', 'Ada', 'developer', { skill: 'backend', role: 'reviewer' })],
      decisions: [{ decision_id: 'd', meeting_id: 'k', title: 'Alerts wait', context: '', alternatives: [], selected_option: 'wait', status: 'accepted', decided_by: null, proposed_by: null, reason: '', timestamp: null }],
      action_items: [{ action_item_id: 'a1', meeting_id: 'k', owner_id: 'a', description: 'Write tests', status: 'done', due_reference: 'sprint 1', created_at: null, completed_at: null }],
    });
    const md = recapMarkdown(view);
    expect(md).toContain('# Discovery: Jarvis');
    expect(md).toContain('- Ada [backend] (reviewer)');
    expect(md).toContain('- **Alerts wait** — accepted: wait');
    expect(md).toContain('- [x] Write tests — Ada, due sprint 1');
    expect(md.endsWith('\n')).toBe(true);
    expect(busiest(view, [wire(1, 'statement', {}, { actor_id: 'a' }), wire(2, 'challenge', {}, { actor_id: 'a' })])[0]).toMatchObject({ lines: 2 });
  });

  it('gives the same person the same look, and the Business SME and the Scrum Master a look of their own', () => {
    expect(lookFor('dev-1', 'developer')).toEqual(lookFor('dev-1', 'developer'));
    expect(lookFor('dev-1', 'developer')).not.toEqual(lookFor('dev-2', 'developer'));
    expect(lookFor('x', 'business_sme').accessory).toBe('tie');
    expect(lookFor('y', 'scrum_master').accessory).toBe('headset');
  });

  it('keeps people in a steady order: the Business SME, the Scrum Master, then the developers in number order', () => {
    const people = [...developers(11).reverse(), person('sm', 'SM', 'scrum_master'), person('sme', 'SME', 'business_sme')];
    expect(tileOrder(people).map((p) => p.participant_id)).toEqual(['sme', 'sm', ...Array.from({ length: 11 }, (_, i) => `dev-${i + 1}`)]);
  });
});
