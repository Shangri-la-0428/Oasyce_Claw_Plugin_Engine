/**
 * Toast — 通知条
 */
import { toasts } from '../store/ui';

export default function ToastContainer() {
  if (!toasts.value.length) return null;
  return (
    <div class="toast-wrap" role="status" aria-live="polite">
      {toasts.value.map(t => (
        <div key={t.id} class={`toast toast-${t.type}`}>
          <span>{t.type === 'success' ? '✓' : t.type === 'error' ? '✕' : '→'}</span>
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  );
}
