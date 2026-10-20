/** What the Standup screen reads: the view of one meeting, the list of meetings, and the API that supplies both (mirrors standup/presentation.py and gateway/standup_routes.py). */
import type { MeetingEventWire, JumpKind } from './meeting-events';
import { MEETING_EVENT_TYPES } from './meeting-events';
import type { ControlMode, MeetingStatus, ParticipantStatus } from './meeting-status';

export interface StandupQuestion {
  question_id: string;
  meeting_id: string;
  asked_by: string | null;
  target: string;
  text: string;
  status: 'open' | 'answered';
  answer: string | null;
  answered_by: string | null;
  options: string[];
  recommended: string | null;
  asked_at: string | null;
  answered_at: string | null;
}

export interface StandupDecision {
  decision_id: string;
  meeting_id: string;
  title: string;
  context: string;
  alternatives: string[];
  selected_option: string | null;
  status: 'proposed' | 'accepted' | 'rejected' | 'deferred';
  decided_by: string | null;
  proposed_by: string | null;
  reason: string;
  timestamp: string | null;
}

export interface StandupActionItem {
  action_item_id: string;
  meeting_id: string;
  owner_id: string;
  description: string;
  status: 'open' | 'in_progress' | 'done' | 'dropped';
  due_reference: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface StandupDocumentReview {
  document_path: string;
  meeting_id: string;
  reviewer_id: string | null;
  status: 'in_review' | 'approved' | 'changes_requested';
  comments: string[];
  reviewed_at: string | null;
}

export interface StandupApproval {
  request_id: string;
  subject: string;
  requested_by: string | null;
  open: boolean;
  approved: boolean | null;
  comment: string;
  extra: { kind?: string; context?: string; options?: string[] } & Record<string, unknown>;
}

export interface StandupParticipant {
  participant_id: string;
  display_name: string;
  participant_type: string;
  skill: string | null;
  role: string | null;
  status: ParticipantStatus;
  badge: string;
  speaking: boolean;
  needs_sme: boolean;
}

export type Tone = 'plain' | 'warn' | 'danger' | 'success' | 'ask' | 'info';

export interface StandupTimelineEntry {
  sequence: number;
  event_type: string;
  kind: string;
  elapsed: string;
  actor_id: string | null;
  actor_name: string;
  text: string;
  tone: Tone;
}

export interface StandupRisk { risk_id: string; text: string; severity: string; raised_by: string | null }
export interface StandupDependency { dependency_id: string; text: string; from_id: string | null; to_id: string | null; identified_by: string | null }

export interface StandupView {
  meeting_id: string;
  title: string;
  meeting_type: string;
  status: MeetingStatus;
  control_mode: ControlMode;
  started_at: string | null;
  elapsed_seconds: number;
  elapsed: string;
  remaining_seconds: number | null;
  paused: boolean;
  current_topic: string | null;
  active_speaker: string | null;
  pending_question: StandupQuestion | null;
  open_questions: StandupQuestion[];
  participants: StandupParticipant[];
  decisions: StandupDecision[];
  action_items: StandupActionItem[];
  reviews: StandupDocumentReview[];
  risks: StandupRisk[];
  dependencies: StandupDependency[];
  approvals_open: StandupApproval[];
  summary: string;
  last_sequence: number;
  recent: StandupTimelineEntry[];
}

/** One row of the meeting list. */
export interface StandupMeetingRow {
  meeting_id: string;
  workspace_id: string;
  title: string;
  meeting_type: string;
  status: MeetingStatus;
  control_mode: ControlMode;
  started_at: string | null;
  ended_at: string | null;
  duration_limit_seconds: number | null;
  open_questions: number;
  decisions: number;
  action_items: number;
  participants: number;
  last_sequence: number;
}

export interface StandupListing {
  record: string;
  records: string[];
  autopilot: boolean;
  meetings: StandupMeetingRow[];
}

export interface StandupViewResponse { view: StandupView; lastSequence: number; record: string }
export interface StandupEventsResponse { meetingId: string; events: MeetingEventWire[]; more: boolean; lastSequence: number }

/** The health of a live stream: "connected" once frames arrive, "reconnecting" after a drop (the browser retries and resumes from the last sequence), "ended" when the meeting is over. */
export type StreamState = 'connecting' | 'connected' | 'reconnecting' | 'ended' | 'closed';

export interface StandupStreamHandlers {
  onEvent: (event: MeetingEventWire) => void;
  onState: (state: StreamState) => void;
}

export interface ViewOptions { at?: number; record?: string }

/** Everything the screen asks of a backend. A real one talks to the gateway; the demo one serves recorded meetings. Components use it only through the workspace repository. */
export interface StandupApi {
  listMeetings(workspaceId: string, record?: string): Promise<StandupListing>;
  getMeeting(workspaceId: string, meetingId: string, options?: ViewOptions): Promise<StandupViewResponse>;
  getEvents(workspaceId: string, meetingId: string, after?: number, record?: string): Promise<StandupEventsResponse>;
  getTranscript(workspaceId: string, meetingId: string, record?: string): Promise<string>;
  answer(workspaceId: string, meetingId: string, questionId: string, answer: string): Promise<void>;
  direct(workspaceId: string, meetingId: string, text: string): Promise<{ accepted: boolean; note?: string }>;
  setControl(workspaceId: string, mode: ControlMode): Promise<{ mode: ControlMode; meetingsTold: number }>;
  /** Streams a meeting live from just after `after`. Returns a function that stops it. */
  stream(workspaceId: string, meetingId: string, after: number, handlers: StandupStreamHandlers): () => void;
}

export type { JumpKind };

// ---------------------------------------------------------------------------------------------- runtime checks: a backend that changes shape fails loudly here, not as a blank screen

function fail(what: string, detail: string): never {
  throw new Error(`Unexpected ${what} from the backend: ${detail}`);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseMeetingEvent(value: unknown): MeetingEventWire {
  if (!isObject(value)) return fail('meeting event', 'not an object');
  for (const key of ['event_id', 'event_type', 'meeting_id', 'workspace_id', 'timestamp', 'correlation_id'] as const) {
    if (typeof value[key] !== 'string') return fail('meeting event', `${key} is not a string`);
  }
  if (!Number.isInteger(value.sequence_number) || (value.sequence_number as number) < 1) return fail('meeting event', 'sequence_number is not a positive integer');
  if (typeof value.elapsed_seconds !== 'number' || value.elapsed_seconds < 0) return fail('meeting event', 'elapsed_seconds is not a non-negative number');
  if (!Number.isInteger(value.schema_version)) return fail('meeting event', 'schema_version is not an integer');
  if (!isObject(value.payload)) return fail('meeting event', 'payload is not an object');
  return value as unknown as MeetingEventWire;
}

export function parseStandupView(value: unknown): StandupView {
  if (!isObject(value)) return fail('meeting view', 'not an object');
  for (const key of ['meeting_id', 'title', 'meeting_type', 'status', 'control_mode', 'elapsed'] as const) {
    if (typeof value[key] !== 'string') return fail('meeting view', `${key} is not a string`);
  }
  for (const key of ['participants', 'open_questions', 'decisions', 'action_items', 'reviews', 'risks', 'dependencies', 'approvals_open', 'recent'] as const) {
    if (!Array.isArray(value[key])) return fail('meeting view', `${key} is not a list`);
  }
  if (typeof value.elapsed_seconds !== 'number' || typeof value.last_sequence !== 'number' || typeof value.paused !== 'boolean') return fail('meeting view', 'a number or flag is missing');
  return value as unknown as StandupView;
}

export function parseListing(value: unknown): StandupListing {
  if (!isObject(value) || !Array.isArray(value.meetings) || !Array.isArray(value.records)) return fail('meeting list', 'meetings or records is missing');
  for (const row of value.meetings) {
    if (!isObject(row) || typeof row.meeting_id !== 'string' || typeof row.title !== 'string' || typeof row.status !== 'string') return fail('meeting list', 'a row has no id, title or status');
  }
  return { record: String(value.record ?? ''), records: value.records as string[], autopilot: value.autopilot === true, meetings: value.meetings as StandupMeetingRow[] };
}

export function knownEventTypes(): readonly string[] {
  return MEETING_EVENT_TYPES;
}
