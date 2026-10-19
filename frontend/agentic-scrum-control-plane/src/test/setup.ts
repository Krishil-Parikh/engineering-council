import '@testing-library/jest-dom/vitest';
import { configure } from '@testing-library/react';

// The Control Plane view is loaded on demand; the first render pulls its code in, which can take longer than the 1s default on a busy machine.
configure({ asyncUtilTimeout: 5000 });

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe(): void { undefined; }
    unobserve(): void { undefined; }
    disconnect(): void { undefined; }
  } as unknown as typeof ResizeObserver;
}

if (typeof window !== 'undefined' && typeof window.matchMedia === 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

if (typeof window !== 'undefined' && !window.requestAnimationFrame) {
  window.requestAnimationFrame = (callback: FrameRequestCallback) => window.setTimeout(callback, 0) as unknown as number;
  window.cancelAnimationFrame = (id: number) => window.clearTimeout(id);
}

if (typeof navigator !== 'undefined' && !navigator.clipboard) {
  Object.defineProperty(navigator, 'clipboard', {
    writable: true,
    value: { writeText: async () => undefined },
  });
}
