import { afterEach, describe, expect, it, vi } from 'vitest';
import { MockStandupApi } from '../../adapters/mockStandupApi';

const W = 'workspace-demo';
let api: MockStandupApi;
afterEach(() => { api?.dispose(); vi.useRealTimers(); });

describe('the demo meetings', () => {
  it('lists a finished discovery meeting and a planning meeting that is waiting for the Business SME', async () => {
    api = new MockStandupApi();
    const { meetings, records } = await api.listMeetings();
    expect(records).toEqual(['demo']);
    const byId = Object.fromEntries(meetings.map((m) => [m.meeting_id, m]));
    expect(byId.discovery.status).toBe('completed');
    expect(byId['s1-planning'].status).toBe('waiting_for_sme');
    expect(byId['s1-planning'].open_questions).toBe(1);
    expect(byId['s1-planning'].participants).toBe(10); // eight developers, the scrum master and the Business SME: the screen assumes no number
  });

  it('shows the state at any point of a recorded meeting, with the conversation up to that point', async () => {
    api = new MockStandupApi();
    const early = await api.getMeeting(W, 'discovery', { at: 12 });
    expect(early.lastSequence).toBe(12);
    expect(early.view.status).toBe('active');
    expect(early.view.recent.every((r) => r.sequence <= 12)).toBe(true);
    const end = await api.getMeeting(W, 'discovery');
    expect(end.view.status).toBe('completed');
    expect(end.view.recent.length).toBeLessThanOrEqual(40);
    expect(end.view.decisions[0]).toMatchObject({ status: 'accepted', selected_option: 'wait' });
    const events = await api.getEvents(W, 'discovery', 30);
    expect(events.events.every((e) => e.sequence_number > 30)).toBe(true);
    expect(await api.getTranscript(W, 'discovery')).toContain('Alerts wait while Jarvis speaks or listens');
    await expect(api.getMeeting(W, 'nope')).rejects.toThrow('No meeting nope');
  });

  it('lets two developers hold the same skill, and the same developer hold another skill in another meeting', async () => {
    api = new MockStandupApi();
    const planning = (await api.getMeeting(W, 's1-planning')).view;
    const skills = planning.participants.filter((p) => p.participant_type === 'developer').map((p) => p.skill);
    expect(skills.filter((s) => s === 'backend').length).toBeGreaterThanOrEqual(2);
    const discovery = (await api.getMeeting(W, 'discovery')).view;
    expect(discovery.participants.filter((p) => p.participant_type === 'developer').every((p) => p.skill === null)).toBe(true); // meeting 1: generic developers
  });

  it('carries on after the question is answered, event by event', async () => {
    vi.useFakeTimers();
    api = new MockStandupApi({ stepMs: 100 });
    const seen: number[] = [];
    api.stream(W, 's1-planning', 0, { onEvent: (e) => seen.push(e.sequence_number), onState: () => undefined });
    await vi.advanceTimersByTimeAsync(0);
    const before = seen.length;
    expect(before).toBe(26);
    await api.answer(W, 's1-planning', 'q-2', '10');
    expect(seen.length).toBe(before + 1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(seen.length).toBe(32);
    expect(seen).toEqual([...seen].sort((a, b) => a - b));
    expect((await api.getMeeting(W, 's1-planning')).view.status).toBe('completed');
    await expect(api.answer(W, 's1-planning', 'q-2', 'again')).rejects.toThrow('not waiting');
  });

  it('answers by itself when the autopilot is on, and goes back to waiting when the person takes over', async () => {
    vi.useFakeTimers();
    api = new MockStandupApi({ stepMs: 10, autopilotMs: 500 });
    expect((await api.setControl(W, 'autopilot')).meetingsTold).toBe(1);
    expect((await api.getMeeting(W, 's1-planning')).view.control_mode).toBe('autopilot');
    await vi.advanceTimersByTimeAsync(1000);
    expect((await api.getMeeting(W, 's1-planning')).view.open_questions).toHaveLength(0);

    api.dispose();
    api = new MockStandupApi({ stepMs: 10, autopilotMs: 500 });
    await api.setControl(W, 'autopilot');
    await api.setControl(W, 'human');
    await vi.advanceTimersByTimeAsync(1000);
    expect((await api.getMeeting(W, 's1-planning')).view.open_questions).toHaveLength(1);
  });

  it('tells a late subscriber everything it missed and that a finished meeting is over', async () => {
    vi.useFakeTimers();
    api = new MockStandupApi();
    const got: number[] = [];
    const states: string[] = [];
    api.stream(W, 'discovery', 30, { onEvent: (e) => got.push(e.sequence_number), onState: (s) => states.push(s) });
    await vi.advanceTimersByTimeAsync(0);
    expect(got[0]).toBe(31);
    expect(states).toEqual(['connecting', 'connected', 'ended']);
  });
});
