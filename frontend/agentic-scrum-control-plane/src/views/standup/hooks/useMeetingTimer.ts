import { useEffect, useState } from 'react';
import { isOver } from '../models/meeting-status';
import type { StandupView } from '../models/standup';
import { elapsedNow, remainingNow } from '../state/standupStore';

/** The meeting clock on the screen: counts on every second from what the server last said, and stands still when the meeting is paused or over. */
export function useMeetingTimer(view: StandupView | null, receivedAt: number, now: () => number = Date.now) {
  const [tick, setTick] = useState(() => now());
  const running = Boolean(view) && view!.started_at !== null && !view!.paused && !isOver(view!.status);

  useEffect(() => {
    setTick(now());
    if (!running) return undefined;
    const id = setInterval(() => setTick(now()), 1000);
    return () => clearInterval(id);
  }, [running, view, receivedAt, now]);

  const elapsed = elapsedNow(view, receivedAt, tick);
  const remaining = remainingNow(view, receivedAt, tick);
  return { elapsed, remaining, running, overtime: remaining !== null && remaining <= 0 && running };
}
