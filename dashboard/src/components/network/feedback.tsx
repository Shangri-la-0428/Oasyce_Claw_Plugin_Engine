import { useState, useEffect } from 'preact/hooks';
import { get, post } from '../../api/client';
import { showToast, i18n } from '../../store/ui';
import { maskIdShort, fmtDate } from '../../utils';
import { EmptyState } from '../empty-state';
import { Section } from '../section';

interface FeedbackItem {
  feedback_id: string;
  type: string;
  message: string;
  context: string;
  agent_id: string;
  status: string;
  created_at: number;
}

export function FeedbackSection({ forceOpen }: { forceOpen: boolean }) {
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [loading, setLoading] = useState(false);

  /* Submit form */
  const [message, setMessage] = useState('');
  const [fbType, setFbType] = useState('bug');
  const [agentId, setAgentId] = useState('');
  const [context, setContext] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const _ = i18n.value;

  const loadFeedback = async () => {
    setLoading(true);
    const res = await get<{ feedback: FeedbackItem[] }>('/feedback');
    if (res.success && Array.isArray(res.data?.feedback)) setItems(res.data.feedback);
    setLoading(false);
  };

  useEffect(() => { loadFeedback(); }, []);

  const onSubmit = async () => {
    if (!message.trim()) return;
    setSubmitting(true);
    let ctx = {};
    if (context.trim()) {
      try { ctx = JSON.parse(context); } catch { /* ignore */ }
    }
    const res = await post<{ ok: boolean; feedback_id: string }>('/feedback', {
      message: message.trim(),
      type: fbType,
      agent_id: agentId || 'dashboard',
      context: ctx,
    });
    if (res.success && res.data?.ok) {
      showToast(_['feedback-success'], 'success');
      setMessage(''); setContext('');
      loadFeedback();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setSubmitting(false);
  };

  const statusClass = (s: string) => {
    if (s === 'resolved') return 'color-green';
    if (s === 'dismissed') return 'color-red';
    return 'fg-muted';
  };

  return (
    <Section id="feedback" title={_['feedback']} desc={_['feedback-desc']} forceOpen={forceOpen}>
      {/* Submit form */}
      <div class="col gap-8 mb-16">
        <textarea
          class="input input-textarea"
          placeholder={_['feedback-message-hint']}
          value={message}
          onInput={e => setMessage((e.target as HTMLTextAreaElement).value)}
          rows={3}
        />
        <div class="row gap-8">
          <select class="input" value={fbType} onChange={e => setFbType((e.target as HTMLSelectElement).value)}>
            <option value="bug">{_['feedback-type-bug']}</option>
            <option value="suggestion">{_['feedback-type-suggestion']}</option>
            <option value="other">{_['feedback-type-other']}</option>
          </select>
          <input
            class="input grow"
            type="text"
            placeholder={_['feedback-agent-hint']}
            value={agentId}
            onInput={e => setAgentId((e.target as HTMLInputElement).value)}
          />
        </div>
        <input
          class="input"
          type="text"
          placeholder={_['feedback-context-hint']}
          value={context}
          onInput={e => setContext((e.target as HTMLInputElement).value)}
        />
        <button
          class="btn btn-primary"
          onClick={onSubmit}
          disabled={submitting || !message.trim()}
        >
          {submitting ? _['feedback-submitting'] : _['feedback-submit']}
        </button>
      </div>

      {/* List */}
      <div class="caption mb-8">{_['feedback-list']}</div>

      {loading && <div class="caption fg-muted">{_['loading']}</div>}

      {!loading && items.length === 0 && (
        <EmptyState icon="✉" title={_['feedback-no-items']} hint={_['feedback-no-items-hint']} />
      )}

      {!loading && items.length > 0 && (
        <div class="col gap-8">
          {items.map(fb => (
            <div key={fb.feedback_id} class="card">
              <div class="row gap-8" style={{ alignItems: 'baseline' }}>
                <span class="mono text-sm">{maskIdShort(fb.feedback_id)}</span>
                <span class="badge">{fb.type}</span>
                <span class={statusClass(fb.status)}>{fb.status}</span>
                <span class="caption fg-muted ml-auto">{fmtDate(fb.created_at, 'datetime')}</span>
              </div>
              <div class="mt-4">{fb.message}</div>
              {fb.agent_id && fb.agent_id !== 'anonymous' && (
                <div class="caption fg-muted mt-4">{_['feedback-agent']}: {fb.agent_id}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
