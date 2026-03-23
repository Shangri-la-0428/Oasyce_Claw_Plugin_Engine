import type { ComponentChildren } from 'preact';

/** Shared empty-state display: icon + title + optional hint + optional action. */
export function EmptyState({ icon, title, hint, children }: {
  icon: string;
  title: string;
  hint?: string;
  children?: ComponentChildren;
}) {
  return (
    <div class="empty-state">
      <div class="empty-state-icon" aria-hidden="true">{icon}</div>
      <div class="empty-state-title">{title}</div>
      {hint && <div class="empty-state-hint">{hint}</div>}
      {children}
    </div>
  );
}
