/** Small pure helpers behind the Standup hooks: time on the screen and the pace of a replay. No React in here, so they are easy to test. */
import type { MeetingEventWire } from '../models/meeting-events';
import type { StandupView } from '../models/standup';
import { isOver } from '../models/meeting-status';

export const REPLAY_SPEEDS = [0.5, 1, 2, 4, 8] as const;
export type ReplaySpeed = (typeof REPLAY_SPEEDS)[number];

const MIN_STEP_MS = 120;
const MAX_STEP_MS = 1800;

/** How long a replay waits before showing event `next` after event `current`: the real gap between them, sped up, but never so long that it feels stuck nor so short that it blurs. */
export function replayDelay(current: MeetingEventWire | undefined, next: MeetingEventWire | undefined, speed: number): number {
  if (!current || !next) return MIN_STEP_MS;
  const gap = Math.max(0, next.elapsed_seconds - current.elapsed_seconds) * 1000;
  return Math.min(MAX_STEP_MS, Math.max(MIN_STEP_MS, gap / Math.max(0.1, speed)));
}

/** Seconds on the meeting clock now: what the server said when it sent the view, plus the time since, while the meeting is running. */
export function elapsedNow(view: StandupView | null, receivedAt: number, now: number): number {
  if (!view) return 0;
  const running = view.started_at !== null && !view.paused && !isOver(view.status);
  return view.elapsed_seconds + (running ? Math.max(0, (now - receivedAt) / 1000) : 0);
}

export function remainingNow(view: StandupView | null, receivedAt: number, now: number): number | null {
  if (!view || view.remaining_seconds === null) return null;
  const running = view.started_at !== null && !view.paused && !isOver(view.status);
  return Math.max(0, view.remaining_seconds - (running ? Math.max(0, (now - receivedAt) / 1000) : 0));
}

export function clampSequence(value: number, events: readonly MeetingEventWire[]): number {
  if (events.length === 0) return 0;
  return Math.min(events[events.length - 1].sequence_number, Math.max(events[0].sequence_number, Math.round(value)));
}

/** The entry that comes `delta` events after sequence `from` (events are in order and numbered from 1 without gaps, but a page may start later). */
export function stepSequence(events: readonly MeetingEventWire[], from: number, delta: number): number {
  const index = events.findIndex((e) => e.sequence_number >= from);
  if (index < 0) return events.length ? events[events.length - 1].sequence_number : 0;
  const target = Math.min(events.length - 1, Math.max(0, index + delta));
  return events[target].sequence_number;
}
