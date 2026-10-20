import { useCallback, useEffect, useRef, useState } from 'react';
import { findJump } from '../models/meeting-events';
import type { JumpKind, MeetingEventWire } from '../models/meeting-events';
import type { StandupApi, StandupView } from '../models/standup';
import { clampSequence, replayDelay, stepSequence } from '../state/standupStore';
import type { ReplaySpeed } from '../state/standupStore';

const VIEW_DEBOUNCE_MS = 80;

export interface MeetingReplay {
  position: number;
  total: number;
  playing: boolean;
  speed: ReplaySpeed;
  view: StandupView | null;
  loading: boolean;
  error: string | null;
  atStart: boolean;
  atEnd: boolean;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (sequence: number) => void;
  step: (delta: number) => void;
  jump: (kind: JumpKind, direction?: 1 | -1) => boolean;
  setSpeed: (speed: ReplaySpeed) => void;
  restart: () => void;
}

/** Walks through a meeting that already happened. The state at each point comes from the backend (`?at=<sequence>`), so a replay shows exactly what the live meeting showed. */
export function useMeetingReplay(
  api: StandupApi | undefined, workspaceId: string, meetingId: string | null, events: readonly MeetingEventWire[], enabled: boolean, record?: string,
): MeetingReplay {
  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<ReplaySpeed>(1);
  const [view, setView] = useState<StandupView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requested = useRef(0);
  const first = events.length ? events[0].sequence_number : 0;
  const last = events.length ? events[events.length - 1].sequence_number : 0;

  // entering replay starts at the beginning; leaving it stops the playback
  useEffect(() => {
    setPlaying(false);
    setPosition(enabled ? first : 0);
    setView(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, meetingId, record]);

  useEffect(() => {
    if (!enabled || !api || !meetingId || position < 1) return undefined;
    const ticket = ++requested.current;
    const id = setTimeout(async () => {
      setLoading(true);
      try {
        const response = await api.getMeeting(workspaceId, meetingId, { at: position, record });
        if (ticket === requested.current) {
          setView(response.view);
          setError(null);
        }
      } catch (caught) {
        if (ticket === requested.current) setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (ticket === requested.current) setLoading(false);
      }
    }, VIEW_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [api, workspaceId, meetingId, record, enabled, position]);

  useEffect(() => {
    if (!enabled || !playing) return undefined;
    if (position >= last) {
      setPlaying(false);
      return undefined;
    }
    const current = events.find((e) => e.sequence_number === position);
    const next = events.find((e) => e.sequence_number > position);
    const id = setTimeout(() => setPosition(next ? next.sequence_number : last), replayDelay(current, next, speed));
    return () => clearTimeout(id);
  }, [enabled, playing, position, speed, events, last]);

  const seek = useCallback((sequence: number) => setPosition(clampSequence(sequence, events)), [events]);
  const step = useCallback((delta: number) => setPosition((p) => stepSequence(events, p, delta)), [events]);

  return {
    position, total: events.length, playing, speed, view, loading, error, atStart: position <= first, atEnd: position >= last,
    play: () => { if (position >= last) setPosition(first); setPlaying(true); },
    pause: () => setPlaying(false),
    toggle: () => { if (playing) setPlaying(false); else { if (position >= last) setPosition(first); setPlaying(true); } },
    seek, step, setSpeed,
    restart: () => { setPosition(first); setPlaying(false); },
    jump: (kind, direction = 1) => {
      const target = findJump(events, position, kind, direction);
      if (target === null) return false;
      setPosition(target);
      setPlaying(false);
      return true;
    },
  };
}
