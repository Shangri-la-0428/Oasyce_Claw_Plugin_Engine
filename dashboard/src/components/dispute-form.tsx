/**
 * DisputeForm — File a dispute for a purchased asset
 * + MyDisputes — List user's disputes
 */
import { useState, useEffect } from 'preact/hooks';
import { post, get } from '../api/client';
import { i18n, walletAddress, showToast, loadNotifications } from '../store/ui';
import { maskIdShort } from '../utils';

interface Dispute {
  dispute_id: string;
  asset_id: string;
  buyer: string;
  reason: string;
  evidence_text: string;
  status: string;
  created_at: number;
  resolved_at: number | null;
  resolution: string | null;
}

const REASONS = [
  'dispute-reason-quality',
  'dispute-reason-mismatch',
  'dispute-reason-copyright',
  'dispute-reason-fraud',
  'dispute-reason-other',
] as const;

interface DisputeFormProps {
  assetId: string;
  onClose: () => void;
  onFiled?: () => void;
}

export function DisputeForm({ assetId, onClose, onFiled }: DisputeFormProps) {
  const [reason, setReason] = useState('');
  const [evidence, setEvidence] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const _ = i18n.value;

  const onSubmit = async () => {
    if (!reason) {
      showToast(_['dispute-reason-select'], 'error');
      return;
    }
    setSubmitting(true);
    const res = await post<{ ok: boolean; dispute_id: string; error?: string }>('/dispute/file', {
      asset_id: assetId,
      reason: _[reason] || reason,
      evidence_text: evidence,
      buyer: walletAddress(),
    });
    if (res.success && res.data?.ok) {
      showToast(_['dispute-filed'], 'success');
      loadNotifications();
      onFiled?.();
      onClose();
    } else {
      showToast(res.error || res.data?.error || _['error-generic'], 'error');
    }
    setSubmitting(false);
  };

  return (
    <div class="dispute-form">
      <div class="dispute-form-title">{_['dispute-file']}</div>
      <div class="dispute-form-asset">
        <span class="kv-key">{_['id']}</span>
        <span class="kv-val mono">{maskIdShort(assetId)}</span>
      </div>

      <label class="label">{_['dispute-reason']}</label>
      <select class="input" value={reason} onChange={e => setReason((e.target as HTMLSelectElement).value)}>
        <option value="">{_['dispute-reason-select']}</option>
        {REASONS.map(r => (
          <option key={r} value={r}>{_[r]}</option>
        ))}
      </select>

      <label class="label mt-12">{_['dispute-evidence']}</label>
      <textarea
        class="input input-textarea"
        value={evidence}
        onInput={e => setEvidence((e.target as HTMLTextAreaElement).value)}
        placeholder={_['dispute-evidence-hint']}
        rows={4}
      />

      <div class="row gap-12 mt-16">
        <button class="btn btn-ghost grow" onClick={onClose}>{_['cancel']}</button>
        <button class="btn btn-primary grow" onClick={onSubmit} disabled={submitting}>
          {submitting ? _['dispute-submitting'] : _['dispute-confirm']}
        </button>
      </div>
    </div>
  );
}

export function MyDisputes() {
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [loading, setLoading] = useState(true);
  const _ = i18n.value;

  useEffect(() => {
    loadDisputes();
  }, []);

  const loadDisputes = async () => {
    setLoading(true);
    const addr = walletAddress();
    if (addr === 'anonymous') { setLoading(false); return; }
    const res = await get<{ disputes: Dispute[] }>(`/disputes?buyer=${encodeURIComponent(addr)}`);
    if (res.success && res.data?.disputes) {
      setDisputes(res.data.disputes);
    }
    setLoading(false);
  };

  const formatTime = (ts: number) => new Date(ts * 1000).toLocaleDateString();

  const statusLabel = (s: string) => {
    if (s === 'open') return _['dispute-open'];
    if (s === 'resolved') return _['dispute-resolved'];
    return s;
  };

  return (
    <div class="my-disputes">
      <h3 class="label-inline mb-12">{_['my-disputes']}</h3>
      {loading ? (
        <div class="skeleton skeleton-md mb-8" />
      ) : disputes.length === 0 ? (
        <div class="caption fg-muted">{_['dispute-no-disputes']}</div>
      ) : (
        <div class="dispute-list">
          {disputes.map(d => (
            <div key={d.dispute_id} class="dispute-item">
              <div class="dispute-item-header">
                <span class="mono">{maskIdShort(d.asset_id)}</span>
                <span class={`dispute-status dispute-status-${d.status}`}>{statusLabel(d.status)}</span>
              </div>
              <div class="dispute-item-reason">{d.reason}</div>
              {d.evidence_text && <div class="dispute-item-evidence">{d.evidence_text}</div>}
              <div class="dispute-item-time">{formatTime(d.created_at)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
