import { describe, expect, it } from 'vitest';
import discovery from '../../fixtures/discovery.json';
import planning from '../../fixtures/planning.json';
import { MEETING_EVENT_TYPES, findJump, isKnownEventType, lastSequence, mergeEvents } from '../../models/meeting-events';
import { formatClock, isOver, meetingTypeLabel, statusLabel, statusTone } from '../../models/meeting-status';
import { initials, participantName } from '../../models/lookup';
import { parseListing, parseMeetingEvent, parseStandupView } from '../../models/standup';
import { clampSequence, elapsedNow, remainingNow, replayDelay, stepSequence } from '../../state/standupStore';
import { makeView, person, wire } from '../helpers';

describe('the event list', () => {
  it('keeps events once each, in order, however they arrive', () => {
    const a = [wire(1, 'meeting_created'), wire(2, 'meeting_started')];
    const merged = mergeEvents(a, [wire(4, 'statement'), wire(3, 'statement'), wire(2, 'meeting_started')]);
    expect(merged.map((e) => e.sequence_number)).toEqual([1, 2, 3, 4]);
    expect(mergeEvents(merged, [wire(3, 'statement')])).toBe(merged); // nothing new: the same list, so nothing re-renders
    expect(mergeEvents(merged, [])).toBe(merged);
    expect(lastSequence(merged)).toBe(4);
    expect(lastSequence([])).toBe(0);
  });

  it('finds the next and the previous decision, question or intervention', () => {
    const events = [wire(1, 'meeting_started'), wire(2, 'decision_proposed'), wire(3, 'statement'), wire(4, 'clarification_requested'), wire(5, 'decision_accepted'), wire(6, 'facilitator_intervention')];
    expect(findJump(events, 0, 'decision')).toBe(2);
    expect(findJump(events, 2, 'decision')).toBe(5);
    expect(findJump(events, 5, 'decision')).toBeNull();
    expect(findJump(events, 5, 'decision', -1)).toBe(2);
    expect(findJump(events, 1, 'question')).toBe(4);
    expect(findJump(events, 3, 'intervention')).toBe(6);
    expect(findJump(events, 1, 'intervention', -1)).toBeNull();
  });

  it('knows the contract, and tolerates a kind it does not know', () => {
    expect(new Set(MEETING_EVENT_TYPES).size).toBe(MEETING_EVENT_TYPES.length);
    expect(isKnownEventType('statement')).toBe(true);
    expect(isKnownEventType('hologram_started')).toBe(false);
    expect(parseMeetingEvent(wire(1, 'hologram_started')).event_type).toBe('hologram_started'); // a newer backend must not break this screen
  });
});

describe('what the backend sends is checked', () => {
  it('refuses an event or a view of the wrong shape, saying what is wrong', () => {
    expect(() => parseMeetingEvent(null)).toThrow(/not an object/);
    expect(() => parseMeetingEvent({ ...wire(1, 'statement'), sequence_number: 0 })).toThrow(/sequence_number/);
    expect(() => parseMeetingEvent({ ...wire(1, 'statement'), elapsed_seconds: -1 })).toThrow(/elapsed_seconds/);
    expect(() => parseMeetingEvent({ ...wire(1, 'statement'), payload: [] })).toThrow(/payload/);
    expect(() => parseStandupView({ ...makeView(), participants: 'nobody' })).toThrow(/participants is not a list/);
    expect(() => parseStandupView({ ...makeView(), paused: 'no' })).toThrow(/flag is missing/);
    expect(() => parseListing({ meetings: [{ meeting_id: 'x' }], records: [] })).toThrow(/no id, title or status/);
    expect(() => parseListing({})).toThrow(/meetings or records/);
    expect(parseListing({ record: 'r', records: ['r'], meetings: [], autopilot: true }).autopilot).toBe(true);
  });

  it.each([['discovery', discovery], ['planning', planning]])('accepts everything the real backend produced for the %s meeting', (_name, fixture) => {
    const data = fixture as unknown as { events: unknown[]; views: Record<string, unknown>; meeting: unknown };
    expect(data.events.length).toBeGreaterThan(20);
    for (const event of data.events) expect(() => parseMeetingEvent(event)).not.toThrow();
    for (const view of Object.values(data.views)) expect(() => parseStandupView(view)).not.toThrow();
    expect(() => parseListing({ record: 'demo', records: ['demo'], meetings: [data.meeting] })).not.toThrow();
  });

  it('only uses event kinds that are part of the contract, and numbers them without gaps', () => {
    for (const fixture of [discovery, planning] as unknown as { events: { event_type: string; sequence_number: number }[] }[]) {
      expect(fixture.events.every((e) => isKnownEventType(e.event_type))).toBe(true);
      expect(fixture.events.map((e) => e.sequence_number)).toEqual(fixture.events.map((_, i) => i + 1));
    }
  });
});

describe('words and times', () => {
  it('reads statuses and types as people do', () => {
    expect(statusLabel('waiting_for_sme')).toBe('Waiting for the Business SME');
    expect(statusLabel('some_new_status')).toBe('some new status');
    expect(meetingTypeLabel('sprint_retrospective')).toBe('Retrospective');
    expect(statusTone('awaiting_approval')).toBe('attention');
    expect(statusTone('completed')).toBe('done');
    expect(isOver('timed_out')).toBe(true);
    expect(isOver('active')).toBe(false);
    expect(formatClock(3725.9)).toBe('01:02:05');
    expect(formatClock(null)).toBe('00:00:00');
    expect(initials('Developer 03')).toBe('D3');
    expect(initials('Developer 12')).toBe('D12');
    expect(initials('Developer 03')).not.toBe(initials('Developer 04')); // every developer is told apart
    expect(initials('Scrum Master')).toBe('SM');
    expect(participantName([person('a', 'Ada')], 'a')).toBe('Ada');
    expect(participantName([person('a', 'Ada')], 'gone')).toBe('gone');
    expect(participantName([], null)).toBe('Someone');
  });

  it('counts the meeting clock on from what the server said, and stops it when paused or over', () => {
    const view = makeView({ elapsed_seconds: 100, remaining_seconds: 500 });
    expect(elapsedNow(view, 1000, 4000)).toBe(103);
    expect(remainingNow(view, 1000, 4000)).toBe(497);
    expect(elapsedNow(makeView({ paused: true, elapsed_seconds: 100 }), 1000, 9000)).toBe(100);
    expect(elapsedNow(makeView({ status: 'completed', elapsed_seconds: 100 }), 1000, 9000)).toBe(100);
    expect(remainingNow(makeView({ remaining_seconds: null }), 0, 9000)).toBeNull();
    expect(remainingNow(makeView({ remaining_seconds: 2 }), 0, 9000)).toBe(0); // never negative
    expect(elapsedNow(null, 0, 0)).toBe(0);
  });
});

describe('replay pace and position', () => {
  const events = [wire(1, 'a', {}, { elapsed_seconds: 0 }), wire(2, 'b', {}, { elapsed_seconds: 1 }), wire(3, 'c', {}, { elapsed_seconds: 60 }), wire(4, 'd', {}, { elapsed_seconds: 61 })];
  it('waits as long as the meeting did, sped up, never too short or too long', () => {
    expect(replayDelay(events[0], events[1], 1)).toBe(1000);
    expect(replayDelay(events[0], events[1], 8)).toBe(125);
    expect(replayDelay(events[0], events[0], 1)).toBe(120); // no gap: the shortest pause
    expect(replayDelay(events[1], events[2], 1)).toBe(1800);
    expect(replayDelay(events[1], events[2], 0.5)).toBe(1800);
    expect(replayDelay(undefined, events[1], 1)).toBe(120);
  });
  it('steps and clamps within the events that exist', () => {
    expect(stepSequence(events, 2, 1)).toBe(3);
    expect(stepSequence(events, 2, -1)).toBe(1);
    expect(stepSequence(events, 4, 5)).toBe(4);
    expect(stepSequence(events, 1, -5)).toBe(1);
    expect(stepSequence([], 1, 1)).toBe(0);
    expect(clampSequence(99, events)).toBe(4);
    expect(clampSequence(-3, events)).toBe(1);
    expect(clampSequence(2.4, events)).toBe(2);
  });
});
