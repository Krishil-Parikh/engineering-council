import { useEffect, useState } from 'react';
import type { RefObject } from 'react';

/** The width of an element, kept up to date (0 when it cannot be known, as in a test environment): the call screen uses it to switch to one row per person in a narrow window. */
export function useContainerWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    setWidth(el.getBoundingClientRect().width);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width ?? 0));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}
