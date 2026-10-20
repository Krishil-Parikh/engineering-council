import { describe, expect, it, vi } from 'vitest';
import { HttpStandupApi, StandupHttpError } from '../../adapters/workspaceRepository';
import type { StreamState } from '../../models/standup';
import { makeView, row, wire } from '../helpers';

function reply(body: unknown, status = 200) {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers: { 'Content-Type': typeof body === 'string' ? 'text/plain' : 'application/json' } });
}

class FakeEventSource {
  static all: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  private listeners = new Map<string, () => void>();
  constructor(readonly url: string) {
    FakeEventSource.all.push(this);
  }
  addEventListener(name: string, fn: () => void) { this.listeners.set(name, fn); }
  close() { this.closed = true; }
  frame(event: unknown) { this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent); }
  fire(name: string) { this.listeners.get(name)?.(); }
}

function api(fetcher: typeof fetch) {
  FakeEventSource.all = [];
  return new HttpStandupApi('http://gw', fetcher, (url) => new FakeEventSource(url) as unknown as EventSource);
}

describe('the Standup API against the gateway', () => {
  it('asks for the right addresses, with the workspace and meeting encoded', async () => {
    const seen: string[] = [];
    const fetcher = vi.fn(async (url: RequestInfo | URL) => {
      seen.push(String(url));
      if (String(url).includes('/events')) return reply({ meetingId: 'a b', events: [wire(1, 'meeting_created')], more: false, lastSequence: 1 });
      if (String(url).endsWith('/meetings')) return reply({ record: 'r', records: ['r'], autopilot: false, meetings: [row()] });
      if (String(url).includes('/transcript')) return reply('hello transcript');
      return reply({ view: makeView(), lastSequence: 3, record: 'r' });
    }) as unknown as typeof fetch;
    const a = api(fetcher);
    expect((await a.listMeetings('w 1')).meetings).toHaveLength(1);
    await a.getMeeting('w 1', 'a b', { at: 7, record: 'old' });
    const events = await a.getEvents('w 1', 'a b', 5);
    expect(events.events[0].sequence_number).toBe(1);
    expect(await a.getTranscript('w 1', 'a b')).toBe('hello transcript');
    expect(seen).toEqual([
      'http://gw/workspace/w%201/standup/meetings',
      'http://gw/workspace/w%201/standup/meetings/a%20b?at=7&record=old',
      'http://gw/workspace/w%201/standup/meetings/a%20b/events?after=5&limit=1000',
      'http://gw/workspace/w%201/standup/meetings/a%20b/transcript',
    ]);
  });

  it('sends answers, directions and the control mode as JSON', async () => {
    const bodies: { url: string; body: unknown }[] = [];
    const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      bodies.push({ url: String(url), body: JSON.parse(String(init?.body)) });
      if (String(url).endsWith('/control')) return reply({ mode: 'autopilot', meetingsTold: 2 });
      if (String(url).endsWith('/direct')) return reply({ accepted: true, note: 'ok' });
      return reply({ accepted: true });
    }) as unknown as typeof fetch;
    const a = api(fetcher);
    await a.answer('w', 'm', 'q-1', 'No, memory only');
    expect(await a.direct('w', 'm', 'keep it simple')).toEqual({ accepted: true, note: 'ok' });
    expect(await a.setControl('w', 'autopilot')).toEqual({ mode: 'autopilot', meetingsTold: 2 });
    expect(bodies).toEqual([
      { url: 'http://gw/workspace/w/standup/meetings/m/answer', body: { questionId: 'q-1', answer: 'No, memory only' } },
      { url: 'http://gw/workspace/w/standup/meetings/m/direct', body: { text: 'keep it simple' } },
      { url: 'http://gw/workspace/w/standup/control', body: { mode: 'autopilot' } },
    ]);
  });

  it('turns failures into messages a person can read', async () => {
    const notFound = api((async () => reply({ error: { code: 'not_found', message: 'no meeting "x"' } }, 404)) as unknown as typeof fetch);
    await expect(notFound.getMeeting('w', 'x')).rejects.toMatchObject({ status: 404, message: 'no meeting "x"' });
    const down = api((async () => { throw new TypeError('Failed to fetch'); }) as unknown as typeof fetch);
    await expect(down.listMeetings('w')).rejects.toThrow(/could not be reached: Failed to fetch/);
    await expect(down.listMeetings('w')).rejects.toBeInstanceOf(StandupHttpError);
    const plain = api((async () => new Response('boom', { status: 500 })) as unknown as typeof fetch);
    await expect(plain.listMeetings('w')).rejects.toThrow('The backend answered 500');
    const odd = api((async () => reply({ view: { nope: true }, lastSequence: 1 })) as unknown as typeof fetch);
    await expect(odd.getMeeting('w', 'm')).rejects.toThrow(/Unexpected meeting view/);
  });

  it('streams a meeting from where it was, reports its health, and stops when the meeting is over', () => {
    const a = api((async () => reply({})) as unknown as typeof fetch);
    const states: StreamState[] = [];
    const got: number[] = [];
    const stop = a.stream('w', 'kickoff', 12, { onEvent: (e) => got.push(e.sequence_number), onState: (s) => states.push(s) });
    const source = FakeEventSource.all[0];
    expect(source.url).toBe('http://gw/workspace/w/standup/meetings/kickoff/stream?after=12');
    source.onopen?.();
    source.frame(wire(13, 'statement', { text: 'hi' }));
    source.frame('not an event');
    source.onmessage?.({ data: '{broken' } as MessageEvent); // a frame it cannot read is skipped, the stream goes on
    source.frame(wire(14, 'statement', { text: 'again' }));
    source.onerror?.();
    expect(states).toEqual(['connecting', 'connected', 'connected', 'connected', 'reconnecting']);
    expect(got).toEqual([13, 14]);
    source.fire('end');
    expect(source.closed).toBe(true);
    expect(states[states.length - 1]).toBe('ended');
    source.onerror?.();
    expect(states[states.length - 1]).toBe('ended'); // once over, a late error does not say "reconnecting"
    stop();
    expect(states[states.length - 1]).toBe('closed');
  });

  it('can be stopped by the screen', () => {
    const a = api((async () => reply({})) as unknown as typeof fetch);
    const stop = a.stream('w', 'm', 0, { onEvent: () => undefined, onState: () => undefined });
    stop();
    expect(FakeEventSource.all[0].closed).toBe(true);
  });
});
