/** The Standup event contract as the browser reads it (mirrors standup/events.py). A test fails when the two lists differ. */

export const SCHEMA_VERSION = 1;

export const MEETING_EVENT_TYPES = [
  'meeting_created', 'meeting_started', 'meeting_paused', 'meeting_resumed', 'meeting_ended', 'meeting_timed_out', 'meeting_cancelled',
  'participant_joined', 'participant_left', 'skill_selected', 'role_assigned', 'topic_started', 'topic_completed',
  'statement', 'brainstorm', 'proposal', 'challenge', 'counterargument', 'question', 'clarification_requested', 'clarification_answered',
  'risk_raised', 'dependency_identified', 'facilitator_intervention', 'human_takeover', 'autopilot_enabled',
  'decision_proposed', 'decision_accepted', 'decision_rejected', 'decision_deferred', 'action_item_created', 'action_item_updated',
  'document_created', 'document_review_started', 'document_approved', 'document_changes_requested',
  'sme_approval_requested', 'sme_approved', 'sme_rejected', 'participant_blocked', 'participant_unblocked', 'summary_generated',
] as const;

export type MeetingEventType = (typeof MEETING_EVENT_TYPES)[number];

/** One thing that happened in a meeting, exactly as the gateway sends it. */
export interface MeetingEventWire {
  event_id: string;
  /** A string, not the union: a newer backend may send a kind this screen does not know yet, and the screen must keep working. */
  event_type: string;
  meeting_id: string;
  workspace_id: string;
  sequence_number: number;
  timestamp: string;
  elapsed_seconds: number;
  actor_id?: string | null;
  target_id?: string | null;
  payload: Record<string, unknown>;
  schema_version: number;
  correlation_id: string;
  causation_id?: string | null;
  idempotency_key?: string | null;
}

/** Event kinds a person jumps between when they replay a meeting. */
export const JUMP_KINDS = {
  decision: ['decision_proposed', 'decision_accepted', 'decision_rejected', 'decision_deferred'],
  question: ['question', 'clarification_requested', 'clarification_answered', 'sme_approval_requested'],
  intervention: ['facilitator_intervention', 'human_takeover', 'autopilot_enabled', 'meeting_paused', 'meeting_resumed'],
} as const;

export type JumpKind = keyof typeof JUMP_KINDS;

export const MEETING_OVER_EVENTS: readonly string[] = ['meeting_ended', 'meeting_timed_out', 'meeting_cancelled'];

export function isKnownEventType(type: string): type is MeetingEventType {
  return (MEETING_EVENT_TYPES as readonly string[]).includes(type);
}

/** Adds events to a list kept in sequence order, without duplicates (the same event arriving twice, from the stream and from a catch-up, is stored once). */
export function mergeEvents(current: readonly MeetingEventWire[], incoming: readonly MeetingEventWire[]): MeetingEventWire[] {
  if (incoming.length === 0) return current as MeetingEventWire[];
  const bySequence = new Map<number, MeetingEventWire>();
  for (const event of current) bySequence.set(event.sequence_number, event);
  let changed = false;
  for (const event of incoming) {
    if (!bySequence.has(event.sequence_number)) {
      bySequence.set(event.sequence_number, event);
      changed = true;
    }
  }
  return changed ? [...bySequence.values()].sort((a, b) => a.sequence_number - b.sequence_number) : (current as MeetingEventWire[]);
}

/** The highest sequence number in a list, 0 when it is empty (where a catch-up or a reconnect starts from). */
export function lastSequence(events: readonly MeetingEventWire[]): number {
  return events.length ? events[events.length - 1].sequence_number : 0;
}

/** The sequence number of the next event of a kind after `from` (or the previous one before it), else null. */
export function findJump(events: readonly MeetingEventWire[], from: number, kind: JumpKind, direction: 1 | -1 = 1): number | null {
  const wanted = JUMP_KINDS[kind] as readonly string[];
  const hits = events.filter((e) => wanted.includes(e.event_type)).map((e) => e.sequence_number);
  if (direction === 1) return hits.find((s) => s > from) ?? null;
  return [...hits].reverse().find((s) => s < from) ?? null;
}
