import { useState, useEffect, useCallback } from 'preact/hooks';

/**
 * Collapsible card section with localStorage persistence.
 * Used across network, automation, and other pages.
 */
export function Section({ id, title, desc, defaultOpen = false, forceOpen = false, children }: {
  id: string; title: string; desc?: string; defaultOpen?: boolean; forceOpen?: boolean; children: any;
}) {
  const storageKey = `section-${id}`;
  const [open, setOpen] = useState(() => {
    if (forceOpen) return true;
    try {
      const saved = localStorage.getItem(storageKey);
      return saved !== null ? saved === '1' : defaultOpen;
    } catch {
      return defaultOpen;
    }
  });

  useEffect(() => {
    if (forceOpen) setOpen(true);
  }, [forceOpen]);

  const toggle = useCallback(() => {
    setOpen(prev => {
      try { localStorage.setItem(storageKey, prev ? '0' : '1'); } catch { /* private mode */ }
      return !prev;
    });
  }, [storageKey]);

  return (
    <div class="card mb-24">
      <button class="section-toggle" onClick={toggle} aria-expanded={open} aria-controls={`section-${id}`}>
        <div class="section-header">
          <div class="label label-flush">{title}</div>
          {desc && !open && <span class="caption section-peek">{desc}</span>}
        </div>
        <span class={`section-chevron ${open ? 'section-chevron-open' : ''}`}>›</span>
      </button>
      {open && (
        <div id={`section-${id}`} class="section-body">
          {desc && <p class="caption mb-16">{desc}</p>}
          {children}
        </div>
      )}
    </div>
  );
}
