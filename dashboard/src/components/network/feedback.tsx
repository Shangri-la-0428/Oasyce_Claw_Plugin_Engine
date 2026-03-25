import { useState } from 'preact/hooks';
import { post } from '../../api/client';
import { showToast, i18n } from '../../store/ui';
import { Section } from '../section';

export function FeedbackSection({ forceOpen }: { forceOpen: boolean }) {
  const [message, setMessage] = useState('');
  const [fbType, setFbType] = useState('bug');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const _ = i18n.value;

  const onSubmit = async () => {
    if (!message.trim()) return;
    setSubmitting(true);
    const res = await post<{ ok: boolean; feedback_id: string }>('/feedback', {
      message: message.trim(),
      type: fbType,
      agent_id: 'dashboard',
    });
    if (res.success && res.data?.ok) {
      showToast(_['feedback-success'], 'success');
      setMessage('');
      setSubmitted(true);
      setTimeout(() => setSubmitted(false), 3000);
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setSubmitting(false);
  };

  return (
    <Section id="feedback" title={_['feedback']} desc={_['feedback-desc']} forceOpen={forceOpen}>
      {submitted ? (
        <div class="caption fg-muted p-0-24 center">
          {_['feedback-success']}
        </div>
      ) : (
        <div class="col gap-8">
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
            <button
              class="btn btn-primary"
              onClick={onSubmit}
              disabled={submitting || !message.trim()}
            >
              {submitting ? _['feedback-submitting'] : _['feedback-submit']}
            </button>
          </div>
        </div>
      )}
    </Section>
  );
}
