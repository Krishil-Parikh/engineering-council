import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { WorkspaceProvider } from '../../../state/WorkspaceProvider';
import { LiveFakeRepository, idleLiveWorkspace } from '../../../test/liveRepository';
import type { MeetingEventWire } from '../models/meeting-events';
import type { ControlMode } from '../models/meeting-status';
import type {
  StandupApi, StandupEventsResponse, StandupListing, StandupMeetingRow, StandupParticipant, StandupStreamHandlers, StandupView, StandupViewResponse, StreamState, ViewOptions,
} from '../models/standup';
import { StandupView as StandupScreen } from '../components/StandupView';

export const WORKSPACE = 'workspace-live';

export function person(id: string, name: string, type = 'developer', extra: Partial<StandupParticipant> = {}): StandupParticipant {
  return { participant_id: id, display_name: name, participant_type: type, skill: null, role: null, status: 'listening', badge: '', speaking: false, needs_sme: false, ...extra };
}

export function developers(count: number, extra: (i: number) => Partial<StandupParticipant> = () => ({})): StandupParticipant[] {
  return Array.from({ length: count }, (_, k) => person(`dev-${k + 1}`, `Developer ${String(k + 1).padStart(2, '0')}`, 'developer', extra(k + 1)));
}

export function makeView(over: Partial<StandupView> = {}): StandupView {
  return {
    meeting_id: 'kickoff', title: 'Discovery: Jarvis', meeting_type: 'discovery', status: 'active', control_mode: 'human', started_at: '2026-03-02T09:30:00Z', elapsed_seconds: 125, elapsed: '00:02:05',
    remaining_seconds: 3475, paused: false, current_topic: 'What are we building?', active_speaker: null, pending_question: null, open_questions: [], participants: [person('sme', 'Business SME', 'business_sme'), person('sm', 'Scrum Master', 'scrum_master'), ...developers(6)],
    decisions: [], action_items: [], reviews: [], risks: [], dependencies: [], approvals_open: [], summary: '', last_sequence: 3, recent: [], ...over,
  };
}

export function entry(sequence: number, event_type: string, text: string, over: Partial<StandupView['recent'][number]> = {}): StandupView['recent'][number] {
  return { sequence, event_type, kind: `standup.${event_type}`, elapsed: '00:00:10', actor_id: 'dev-1', actor_name: 'Developer 01', text, tone: 'plain', ...over };
}

export function row(over: Partial<StandupMeetingRow> = {}): StandupMeetingRow {
  return {
    meeting_id: 'kickoff', workspace_id: WORKSPACE, title: 'Discovery: Jarvis', meeting_type: 'discovery', status: 'active', control_mode: 'human', started_at: '2026-03-02T09:30:00Z', ended_at: null,
    duration_limit_seconds: 3600, open_questions: 0, decisions: 0, action_items: 0, participants: 8, last_sequence: 3, ...over,
  };
}

export function wire(sequence: number, event_type: string, payload: Record<string, unknown> = {}, over: Partial<MeetingEventWire> = {}): MeetingEventWire {
  return {
    event_id: `evt-${sequence}`, event_type, meeting_id: 'kickoff', workspace_id: WORKSPACE, sequence_number: sequence, timestamp: '2026-03-02T09:30:00Z', elapsed_seconds: sequence * 10, actor_id: 'dev-1',
    target_id: null, payload, schema_version: 1, correlation_id: `cor-${sequence}`, ...over,
  };
}

/** A StandupApi a test controls: what it serves, what it was asked, and the live stream it can push into. */
export class FakeStandupApi implements StandupApi {
  views = new Map<string, StandupView>();
  viewAt: ((meetingId: string, at: number) => StandupView) | null = null;
  eventsByMeeting = new Map<string, MeetingEventWire[]>();
  rows: StandupMeetingRow[] = [];
  records = ['run-1'];
  autopilot = false;
  calls: { method: string; args: unknown[] }[] = [];
  handlers: StandupStreamHandlers | null = null;
  streamOpened: { meetingId: string; after: number }[] = [];
  streamsOpen = 0;
  failList: string | null = null;
  failMeeting: string | null = null;
  failAnswer: string | null = null;
  transcript = '00:00:10 Developer 01 — Statement:\nHello';

  private log(method: string, ...args: unknown[]) {
    this.calls.push({ method, args });
  }

  called(method: string) {
    return this.calls.filter((c) => c.method === method);
  }

  with(view: StandupView, events: MeetingEventWire[] = []) {
    this.views.set(view.meeting_id, view);
    this.eventsByMeeting.set(view.meeting_id, events);
    if (!this.rows.some((r) => r.meeting_id === view.meeting_id)) {
      this.rows.push(row({ meeting_id: view.meeting_id, title: view.title, meeting_type: view.meeting_type, status: view.status, open_questions: view.open_questions.length, last_sequence: view.last_sequence }));
    }
    return this;
  }

  async listMeetings(_w: string, record?: string): Promise<StandupListing> {
    this.log('listMeetings', record);
    if (this.failList) throw new Error(this.failList);
    return { record: 'run-1', records: this.records, autopilot: this.autopilot, meetings: this.rows };
  }

  async getMeeting(_w: string, meetingId: string, options: ViewOptions = {}): Promise<StandupViewResponse> {
    this.log('getMeeting', meetingId, options);
    if (this.failMeeting) throw new Error(this.failMeeting);
    const view = options.at !== undefined && this.viewAt ? this.viewAt(meetingId, options.at) : this.views.get(meetingId);
    if (!view) throw new Error(`No meeting ${meetingId}`);
    return { view, lastSequence: view.last_sequence, record: 'run-1' };
  }

  async getEvents(_w: string, meetingId: string, after = 0): Promise<StandupEventsResponse> {
    this.log('getEvents', meetingId, after);
    const events = (this.eventsByMeeting.get(meetingId) ?? []).filter((e) => e.sequence_number > after);
    return { meetingId, events, more: false, lastSequence: events.length ? events[events.length - 1].sequence_number : after };
  }

  async getTranscript(): Promise<string> {
    this.log('getTranscript');
    return this.transcript;
  }

  async answer(_w: string, meetingId: string, questionId: string, answer: string): Promise<void> {
    this.log('answer', meetingId, questionId, answer);
    if (this.failAnswer) throw new Error(this.failAnswer);
  }

  async direct(_w: string, meetingId: string, text: string) {
    this.log('direct', meetingId, text);
    return { accepted: true, note: 'The team heard you.' };
  }

  async setControl(_w: string, mode: ControlMode) {
    this.log('setControl', mode);
    this.autopilot = mode === 'autopilot';
    for (const [id, view] of this.views) this.views.set(id, { ...view, control_mode: mode }); // the backend records the change, so the next view says so
    return { mode, meetingsTold: 1 };
  }

  stream(_w: string, meetingId: string, after: number, handlers: StandupStreamHandlers): () => void {
    this.log('stream', meetingId, after);
    this.streamOpened.push({ meetingId, after });
    this.streamsOpen += 1;
    this.handlers = handlers;
    handlers.onState('connected');
    return () => {
      this.streamsOpen -= 1;
      handlers.onState('closed');
    };
  }

  push(event: MeetingEventWire) {
    this.handlers?.onEvent(event);
  }

  state(state: StreamState) {
    this.handlers?.onState(state);
  }
}

export function renderStandup(api: StandupApi | undefined, ui: ReactElement = <StandupScreen initialLayout="panels" />) {
  const repository = new LiveFakeRepository(idleLiveWorkspace(WORKSPACE));
  (repository as unknown as { standup?: StandupApi }).standup = api;
  const result = render(<WorkspaceProvider workspaceId={WORKSPACE} repository={repository}>{ui}</WorkspaceProvider>);
  return { repository, ...result };
}
