import { useEffect } from 'preact/hooks';

/** Calls `handler` when Escape is pressed. Only active when `enabled` is true. */
export function useEscapeKey(handler: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') handler(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [handler, enabled]);
}
