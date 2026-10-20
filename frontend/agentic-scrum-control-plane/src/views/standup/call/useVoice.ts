import { useCallback, useEffect, useState } from 'react';

/** An optional voice for the lines, using the browser's own speech (nothing is sent anywhere). Off until asked for: a meeting that starts talking out loud by itself is a bad surprise. */
export function useVoice() {
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window && typeof SpeechSynthesisUtterance !== 'undefined';
  const [enabled, setEnabled] = useState(false);

  const stop = useCallback(() => {
    if (supported) window.speechSynthesis.cancel();
  }, [supported]);

  const speak = useCallback((text: string, rate = 1) => {
    if (!supported || !enabled || !text.trim()) return;
    window.speechSynthesis.cancel(); // one voice at a time: a new line replaces the one before
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = Math.min(2, Math.max(0.7, rate));
    window.speechSynthesis.speak(utterance);
  }, [supported, enabled]);

  useEffect(() => {
    if (!enabled) stop();
    return stop;
  }, [enabled, stop]);

  return { supported, enabled, setEnabled, speak, stop };
}
