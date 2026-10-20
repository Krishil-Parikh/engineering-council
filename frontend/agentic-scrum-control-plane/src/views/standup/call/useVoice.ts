import { useCallback, useEffect, useRef, useState } from 'react';
import { hash } from './script';

export interface SayHandlers { onStart?: () => void; onEnd: () => void }

/** What the call needs from a voice: say one piece of a line as one person, and tell when it starts and ends. */
export interface VoiceDriver {
  enabled: boolean;
  say: (text: string, personId: string | null | undefined, rate: number, handlers: SayHandlers) => () => void;
  stop: () => void;
}

const KEY = 'standup.voice';

function remembered(): boolean {
  try {
    return window.localStorage.getItem(KEY) === 'on';
  } catch {
    return false;
  }
}

/** Each person always sounds the same, and differently from the others: a voice of the browser's English voices, a pitch and a pace, all chosen from their id. */
export function voiceFor(personId: string, voices: readonly SpeechSynthesisVoice[]): { voice: SpeechSynthesisVoice | null; pitch: number; pace: number } {
  const h = hash(personId);
  const english = voices.filter((v) => /^en/i.test(v.lang));
  const pool = english.length ? english : voices;
  return {
    voice: pool.length ? pool[h % pool.length] : null,
    pitch: 0.82 + ((h >>> 5) % 9) * 0.045,
    pace: 0.94 + ((h >>> 9) % 6) * 0.025,
  };
}

/** An optional voice for the lines, using the browser's own speech (nothing is sent anywhere). It is off until asked for, and then remembered: a meeting that starts talking out loud by itself
 *  is a bad surprise, and a browser lets a page speak only after the person has done something on it, so the first click or key press "unlocks" it. */
export function useVoice(): VoiceDriver & { supported: boolean; setEnabled: (on: boolean) => void; voices: number } {
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window && typeof SpeechSynthesisUtterance !== 'undefined';
  const [enabled, setOn] = useState(() => supported && remembered());
  const voices = useRef<SpeechSynthesisVoice[]>([]);
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!supported) return undefined;
    const load = () => {
      voices.current = window.speechSynthesis.getVoices();
      setCount(voices.current.length);
    };
    load();
    window.speechSynthesis.addEventListener?.('voiceschanged', load);
    return () => window.speechSynthesis.removeEventListener?.('voiceschanged', load);
  }, [supported]);

  const stop = useCallback(() => {
    if (supported) window.speechSynthesis.cancel();
  }, [supported]);

  const setEnabled = useCallback((on: boolean) => {
    setOn(on);
    try {
      window.localStorage.setItem(KEY, on ? 'on' : 'off');
    } catch {
      /* not remembered: it is off again next time */
    }
    if (!on && supported) window.speechSynthesis.cancel();
  }, [supported]);

  // a page may speak only after a gesture: the first click or key press says a silent word, which opens it
  useEffect(() => {
    if (!supported || !enabled) return undefined;
    const unlock = () => {
      const quiet = new SpeechSynthesisUtterance(' ');
      quiet.volume = 0;
      window.speechSynthesis.speak(quiet);
    };
    window.addEventListener('pointerdown', unlock, { once: true });
    window.addEventListener('keydown', unlock, { once: true });
    return () => {
      window.removeEventListener('pointerdown', unlock);
      window.removeEventListener('keydown', unlock);
    };
  }, [supported, enabled]);

  const say = useCallback((text: string, personId: string | null | undefined, rate: number, handlers: SayHandlers) => {
    if (!supported || !enabled || !text.trim()) {
      handlers.onEnd();
      return () => undefined;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    const look = voiceFor(personId ?? 'someone', voices.current);
    if (look.voice) utterance.voice = look.voice;
    utterance.pitch = look.pitch;
    utterance.rate = Math.min(2, Math.max(0.7, rate * look.pace));
    let done = false;
    const end = () => {
      if (done) return;
      done = true;
      handlers.onEnd();
    };
    utterance.onstart = () => handlers.onStart?.();
    utterance.onend = end;
    utterance.onerror = end;
    window.speechSynthesis.speak(utterance);
    return () => {
      done = true; // cancelled: no end is reported
      window.speechSynthesis.cancel();
    };
  }, [supported, enabled]);

  useEffect(() => () => stop(), [stop]);

  return { supported, enabled, setEnabled, say, stop, voices: count };
}
