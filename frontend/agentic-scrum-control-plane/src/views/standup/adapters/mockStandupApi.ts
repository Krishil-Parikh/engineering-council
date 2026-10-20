/** The Standup API for demo mode and tests: two recorded meetings, produced by the real backend service (see tests/standup/make_fixtures.py), so the screen shows what the backend
 *  would compute and no meeting rule is written twice. One meeting is already over; the other waits for a Business SME answer and carries on when it is given (or when the
 *  autopilot answers). */
import discovery from '../fixtures/discovery.json';
import planning from '../fixtures/planning.json';
import type { MeetingEventWire } from '../models/meeting-events';
import { isOver } from '../models/meeting-status';
import type { ControlMode } from '../models/meeting-status';
import type {
  StandupApi, StandupEventsResponse, StandupListing, StandupMeetingRow, StandupStreamHandlers, StandupTimelineEntry, StandupView, StandupViewResponse, ViewOptions,
} from '../models/standup';

interface Recorded {
  meeting: StandupMeetingRow;
  events: MeetingEventWire[];
  views: Record<string, StandupView>;
  timeline: StandupTimelineEntry[];
  transcript: string;
  waiting_at: number | null;
}

export interface MockOptions {
  /** Milliseconds between the events that follow an answer. */
  stepMs?: number;
  /** Milliseconds before the autopilot answers a waiting question. */
  autopilotMs?: number;
}

interface Playing {
  data: Recorded;
  cursor: number; // events shown so far
  listeners: Set<(event: MeetingEventWire) => void>;
  timer: ReturnType<typeof setTimeout> | null;
}

export class MockStandupApi implements StandupApi {
  private readonly meetings = new Map<string, Playing>();
  private autopilot = false;
  private readonly handedOver = new Set<string>(); // the meetings that were open when control went to the autopilot: they stay in that mode after they end, as in the backend
  private autopilotTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly stepMs: number;
  private readonly autopilotMs: number;

  constructor(options: MockOptions = {}) {
    this.stepMs = options.stepMs ?? 700;
    this.autopilotMs = options.autopilotMs ?? 2500;
    for (const data of [discovery, planning] as unknown as Recorded[]) {
      const done = data.waiting_at === null;
      this.meetings.set(data.meeting.meeting_id, { data, cursor: done ? data.events.length : (data.waiting_at as number), listeners: new Set(), timer: null });
    }
  }

  private get(meetingId: string): Playing {
    const found = this.meetings.get(meetingId);
    if (!found) throw new Error(`No meeting ${meetingId}`);
    return found;
  }

  private viewAt(p: Playing, at: number): StandupView {
    const base = p.data.views[String(at)];
    const control: ControlMode = this.handedOver.has(p.data.meeting.meeting_id) ? 'autopilot' : base.control_mode;
    return { ...base, control_mode: control, recent: p.data.timeline.filter((t) => t.sequence <= at).slice(-40) };
  }

  private row(p: Playing): StandupMeetingRow {
    const view = this.viewAt(p, p.cursor);
    return {
      ...p.data.meeting, status: view.status, control_mode: view.control_mode, open_questions: view.open_questions.length, decisions: view.decisions.length,
      action_items: view.action_items.length, participants: view.participants.filter((x) => x.status !== 'left').length, last_sequence: p.cursor,
      ended_at: isOver(view.status) ? p.data.meeting.ended_at : null,
    };
  }

  async listMeetings(): Promise<StandupListing> {
    return { record: 'demo', records: ['demo'], autopilot: this.autopilot, meetings: [...this.meetings.values()].map((p) => this.row(p)) };
  }

  async getMeeting(_workspaceId: string, meetingId: string, options: ViewOptions = {}): Promise<StandupViewResponse> {
    const p = this.get(meetingId);
    const at = Math.min(options.at ?? p.cursor, p.cursor);
    return { view: this.viewAt(p, at), lastSequence: at, record: 'demo' };
  }

  async getEvents(_workspaceId: string, meetingId: string, after = 0): Promise<StandupEventsResponse> {
    const p = this.get(meetingId);
    const events = p.data.events.slice(0, p.cursor).filter((e) => e.sequence_number > after);
    return { meetingId, events, more: false, lastSequence: events.length ? events[events.length - 1].sequence_number : after };
  }

  async getTranscript(_workspaceId: string, meetingId: string): Promise<string> {
    const p = this.get(meetingId);
    return p.cursor >= p.data.events.length ? p.data.transcript : p.data.transcript.split('\n').slice(0, p.cursor + 4).join('\n') + '\n';
  }

  async answer(_workspaceId: string, meetingId: string, questionId: string, _answer?: string): Promise<void> {
    const p = this.get(meetingId);
    const open = this.viewAt(p, p.cursor).open_questions.some((q) => q.question_id === questionId);
    if (!open) throw new Error('That question is not waiting for an answer.');
    this.carryOn(p);
  }

  async direct(): Promise<{ accepted: boolean; note?: string }> {
    return { accepted: true, note: 'Demo: the team hears you, nothing changes in the recording.' };
  }

  async setControl(_workspaceId: string, mode: ControlMode): Promise<{ mode: ControlMode; meetingsTold: number }> {
    this.autopilot = mode === 'autopilot';
    for (const [id, p] of this.meetings) {
      if (isOver(this.viewAt(p, p.cursor).status)) continue;
      if (this.autopilot) this.handedOver.add(id);
      else this.handedOver.delete(id);
    }
    if (this.autopilotTimer) clearTimeout(this.autopilotTimer);
    if (this.autopilot) {
      this.autopilotTimer = setTimeout(() => {
        for (const p of this.meetings.values()) {
          if (this.viewAt(p, p.cursor).open_questions.length) this.carryOn(p);
        }
      }, this.autopilotMs);
    }
    return { mode, meetingsTold: [...this.meetings.values()].filter((p) => !isOver(this.viewAt(p, p.cursor).status)).length };
  }

  stream(_workspaceId: string, meetingId: string, after: number, handlers: StandupStreamHandlers): () => void {
    const p = this.get(meetingId);
    handlers.onState('connecting');
    const listener = (event: MeetingEventWire) => handlers.onEvent(event);
    p.listeners.add(listener);
    const timer = setTimeout(() => {
      handlers.onState('connected');
      for (const event of p.data.events.slice(0, p.cursor)) {
        if (event.sequence_number > after) handlers.onEvent(event);
      }
      if (isOver(this.viewAt(p, p.cursor).status)) handlers.onState('ended');
    }, 0);
    return () => {
      clearTimeout(timer);
      p.listeners.delete(listener);
      handlers.onState('closed');
    };
  }

  /** The answer has been given: the rest of the recording plays out, one event at a time. */
  private carryOn(p: Playing): void {
    if (p.timer) return;
    const step = () => {
      p.timer = null;
      if (p.cursor >= p.data.events.length) return;
      const event = p.data.events[p.cursor];
      p.cursor += 1;
      p.listeners.forEach((l) => l(event));
      if (p.cursor < p.data.events.length) p.timer = setTimeout(step, this.stepMs);
    };
    step();
  }

  /** Stops anything still scheduled (tests). */
  dispose(): void {
    if (this.autopilotTimer) clearTimeout(this.autopilotTimer);
    for (const p of this.meetings.values()) if (p.timer) clearTimeout(p.timer);
  }
}
