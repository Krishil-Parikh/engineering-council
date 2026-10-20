import { useCallback, useEffect, useRef, useState } from 'react';
import type { StandupTimelineEntry } from '../models/standup';
import { pieceStarts, speechMs, splitPieces, spokenText } from './script';
import type { VoiceDriver } from './useVoice';

export interface ActiveLine {
  entry: StandupTimelineEntry;
  pieces: string[];
  index: number;
  /** True while the line is being "said"; false once it is done (the last piece stays on screen until the next line). */
  animating: boolean;
}

const MAX_QUEUE = 6;
const KEEP_WHEN_BEHIND = 3;
const VOICE_START_WAIT_MS = 2500; // a voice that has not begun by then is blocked or missing: the piece goes on by the clock instead

/** The lines of a meeting as they would be said: one person at a time, each cut into pieces shown in turn, the next line waiting until the one before has been said.
 *  With the voice on, each piece moves on when its voice has finished it, so the subtitles follow the real speech; without it (or when the browser will not speak) a clock does it.
 *  Live, a line that arrives while another is being said waits its turn, and if the meeting runs far ahead the old ones are dropped so the screen never falls behind.
 *  The first lines it sees (a meeting just opened, or a jump in a replay) are shown whole at once, not played. */
export function useCallScript(
  spoken: readonly StandupTimelineEntry[], playing: boolean, speed: number, resetKey: string, voice?: VoiceDriver,
): { active: ActiveLine | null; queued: number } {
  const [active, setActive] = useState<ActiveLine | null>(null);
  const [queued, setQueued] = useState(0);
  const queue = useRef<StandupTimelineEntry[]>([]);
  const lastSeq = useRef<number | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const cancelVoice = useRef<() => void>(() => undefined);
  const activeRef = useRef<ActiveLine | null>(null);
  const speedRef = useRef(speed);
  const playingRef = useRef(playing);
  const voiceRef = useRef(voice);
  const next = useRef<() => void>(() => undefined);
  speedRef.current = speed;
  playingRef.current = playing;
  voiceRef.current = voice;

  const set = useCallback((value: ActiveLine | null) => {
    activeRef.current = value;
    setActive(value);
  }, []);

  const clear = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    cancelVoice.current();
    cancelVoice.current = () => undefined;
  }, []);

  const finish = useCallback((entry: StandupTimelineEntry) => {
    if (activeRef.current && activeRef.current.entry === entry) set({ ...activeRef.current, animating: false });
    if (queue.current.length) next.current();
  }, [set]);

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
    set({ entry, pieces, index: 0, animating: true });
    const driver = voiceRef.current;
    if (driver?.enabled) {
      const show = (i: number) => {
        if (!activeRef.current || activeRef.current.entry !== entry) return;
        set({ ...activeRef.current, index: i });
        let moved = false;
        const advance = () => {
          if (moved) return;
          moved = true;
          timers.current.forEach(clearTimeout);
          timers.current = [];
          if (i + 1 < pieces.length) show(i + 1);
          else timers.current.push(setTimeout(() => finish(entry), 250));
        };
        const watchdog = setTimeout(() => {
          cancelVoice.current();
          timers.current.push(setTimeout(advance, speechMs(pieces[i], speedRef.current))); // no voice came: say it by the clock
        }, VOICE_START_WAIT_MS);
        timers.current.push(watchdog);
        cancelVoice.current = driver.say(pieces[i], entry.actor_id, speedRef.current, { onStart: () => clearTimeout(watchdog), onEnd: advance });
      };
      show(0);
      return;
    }
    const total = speechMs(text, speedRef.current);
    pieceStarts(pieces, total).forEach((ms, i) => {
      if (i > 0) timers.current.push(setTimeout(() => set(activeRef.current && activeRef.current.entry === entry ? { ...activeRef.current, index: i } : activeRef.current), ms));
    });
    timers.current.push(setTimeout(() => finish(entry), total + 400));
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

  // paused: the line stands still (and falls silent); resumed: it is said again from its start
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

  // the voice was turned off or on in the middle of a line: carry on in the other way, from the start of the line
  const voiceOn = Boolean(voice?.enabled);
  useEffect(() => {
    const current = activeRef.current;
    if (!playingRef.current || !current || !current.animating) return;
    queue.current.unshift(current.entry);
    next.current();
  }, [voiceOn]);

  useEffect(() => clear, [clear]);

  return { active, queued };
}
