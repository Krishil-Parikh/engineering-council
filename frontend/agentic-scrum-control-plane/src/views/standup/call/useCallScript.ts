import { useCallback, useEffect, useRef, useState } from 'react';
import type { StandupTimelineEntry } from '../models/standup';
import { pieceStarts, speechMs, splitPieces, spokenText } from './script';

export interface ActiveLine {
  entry: StandupTimelineEntry;
  pieces: string[];
  index: number;
  /** True while the line is being "said"; false once it is done (the last piece stays on screen until the next line). */
  animating: boolean;
}

const MAX_QUEUE = 6;
const KEEP_WHEN_BEHIND = 3;

/** The lines of a meeting as they would be said: one person at a time, each cut into pieces shown in turn, the next line waiting until the one before has been said.
 *  Live, a line that arrives while another is being said waits its turn, and if the meeting runs far ahead the old ones are dropped so the screen never falls behind.
 *  The first lines it sees (a meeting just opened, or a jump in a replay) are shown whole at once, not played. */
export function useCallScript(spoken: readonly StandupTimelineEntry[], playing: boolean, speed: number, resetKey: string): { active: ActiveLine | null; queued: number } {
  const [active, setActive] = useState<ActiveLine | null>(null);
  const [queued, setQueued] = useState(0);
  const queue = useRef<StandupTimelineEntry[]>([]);
  const lastSeq = useRef<number | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const activeRef = useRef<ActiveLine | null>(null);
  const speedRef = useRef(speed);
  const playingRef = useRef(playing);
  const next = useRef<() => void>(() => undefined);
  speedRef.current = speed;
  playingRef.current = playing;

  const set = useCallback((value: ActiveLine | null) => {
    activeRef.current = value;
    setActive(value);
  }, []);

  const clear = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  }, []);

  next.current = () => {
    clear();
    const entry = queue.current.shift();
    setQueued(queue.current.length);
    if (!entry) return;
    const text = spokenText(entry);
    const pieces = splitPieces(text);
    if (pieces.length === 0) {
      next.current();
      return;
    }
    const total = speechMs(text, speedRef.current);
    set({ entry, pieces, index: 0, animating: true });
    pieceStarts(pieces, total).forEach((ms, i) => {
      if (i > 0) timers.current.push(setTimeout(() => set(activeRef.current && activeRef.current.entry === entry ? { ...activeRef.current, index: i } : activeRef.current), ms));
    });
    timers.current.push(setTimeout(() => {
      if (activeRef.current && activeRef.current.entry === entry) set({ ...activeRef.current, animating: false });
      if (queue.current.length) next.current();
    }, total + 400));
  };

  const showWhole = useCallback((entry: StandupTimelineEntry | undefined) => {
    clear();
    queue.current = [];
    setQueued(0);
    if (!entry) {
      set(null);
      return;
    }
    const pieces = splitPieces(spokenText(entry));
    set({ entry, pieces, index: Math.max(0, pieces.length - 1), animating: false });
  }, [clear, set]);

  // a different meeting: start again
  useEffect(() => {
    lastSeq.current = null;
    showWhole(undefined);
  }, [resetKey, showWhole]);

  useEffect(() => {
    const top = spoken.length ? spoken[spoken.length - 1].sequence : 0;
    if (lastSeq.current === null || top < lastSeq.current) {
      lastSeq.current = top;
      showWhole(spoken[spoken.length - 1]);
      return;
    }
    const fresh = spoken.filter((e) => e.sequence > (lastSeq.current ?? 0));
    if (fresh.length === 0) return;
    lastSeq.current = top;
    if (fresh.length > 8) {
      showWhole(spoken[spoken.length - 1]); // a jump in a replay: no point playing eight lines in a row
      return;
    }
    queue.current.push(...fresh);
    if (queue.current.length > MAX_QUEUE) queue.current = queue.current.slice(-KEEP_WHEN_BEHIND);
    setQueued(queue.current.length);
    if (playingRef.current && (!activeRef.current || !activeRef.current.animating)) next.current();
  }, [spoken, showWhole]);

  // paused: the line stands still; resumed: it is said again from its start
  useEffect(() => {
    if (!playing) {
      clear();
      return;
    }
    const current = activeRef.current;
    if (current && current.animating) {
      queue.current.unshift(current.entry);
      next.current();
    } else if (queue.current.length) {
      next.current();
    }
  }, [playing, clear]);

  useEffect(() => clear, [clear]);

  return { active, queued };
}
