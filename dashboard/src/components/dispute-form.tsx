/**
 * DisputeForm — File a dispute for a purchased asset
 * + MyDisputes — List user's disputes
 */
import { useState, useEffect, useRef } from 'preact/hooks';
import { post, get } from '../api/client';
import { fmtDate } from '../utils';
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
  const [reasonError, setReasonError] = useState('');
  const submittingRef = useRef(false);
  const _ = i18n.value;

  const onSubmit = async () => {
    if (submittingRef.current) return;
    if (!reason) {
      setReasonError(_['dispute-reason-select']);
      showToast(_['dispute-reason-select'], 'error');
      return;
    }
    setReasonError('');
    submittingRef.current = true;
    setSubmitting(true);
    const res = await post<{ ok: boolean; dispute_id: string; error?: string }>('/dispute/file', {
      asset_id: assetId,
      reason: reason,
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
    submittingRef.current = false;
  };

  return (
    <div class="dispute-form">
      <div class="dispute-form-title">{_['dispute-file']}</div>
      <div class="dispute-form-asset">
        <span class="kv-key">{_['id']}</span>
        <span class="kv-val mono">{maskIdShort(assetId)}</span>
      </div>

      <label class="label" htmlFor="dispute-reason">{_['dispute-reason']}</label>
      <select id="dispute-reason" class="input" value={reason} onChange={e => { setReason((e.target as HTMLSelectElement).value); setReasonError(''); }} required aria-required="true" aria-describedby={reasonError ? 'dispute-reason-error' : undefined} aria-invalid={!!reasonError}>
        <option value="">{_['dispute-reason-select']}</option>
        {REASONS.map(r => (
          <option key={r} value={r}>{_[r]}</option>
        ))}
      </select>
      {reasonError && <div id="dispute-reason-error" class="caption style-warn" role="alert">{reasonError}</div>}

      <label class="label mt-12" htmlFor="dispute-evidence">{_['dispute-evidence']}</label>
      <textarea
        id="dispute-evidence"
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

const REMEDIES = ['delist', 'transfer', 'rights_correction', 'share_adjustment'] as const;
const EVIDENCE_TYPES = ['document', 'screenshot', 'log', 'other'] as const;

export function MyDisputes() {
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [loading, setLoading] = useState(true);
  const _ = i18n.value;

  // Jury voting state
  const [votingId, setVotingId] = useState<string | null>(null);
  const [voting, setVoting] = useState(false);

  // Dispute resolution state
  const [resolveId, setResolveId] = useState<string | null>(null);
  const [resolveRemedy, setResolveRemedy] = useState('');
  const [resolveDetails, setResolveDetails] = useState('');
  const [resolving, setResolving] = useState(false);

  // Evidence submission state
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [evidenceHash, setEvidenceHash] = useState('');
  const [evidenceType, setEvidenceType] = useState('');
  const [evidenceDesc, setEvidenceDesc] = useState('');
  const [submittingEvidence, setSubmittingEvidence] = useState(false);

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

  const statusLabel = (s: string) => {
    if (s === 'open') return _['dispute-open'];
    if (s === 'resolved') return _['dispute-resolved'];
    if (s === 'dismissed') return _['dispute-dismissed'];
    return s;
  };

  const onJuryVote = async (disputeId: string, verdict: 'uphold' | 'reject') => {
    setVoting(true);
    const res = await post<{ ok: boolean; error?: string }>('/jury/vote', {
      dispute_id: disputeId,
      juror: walletAddress(),
      verdict,
    });
    if (res.success && res.data?.ok) {
      showToast(_['jury-vote-success'], 'success');
      setVotingId(null);
      loadDisputes();
    } else {
      showToast(res.error || res.data?.error || _['error-generic'], 'error');
    }
    setVoting(false);
  };

  const onResolve = async (assetId: string) => {
    if (!resolveRemedy) return;
    setResolving(true);
    const res = await post<{ ok: boolean; error?: string }>('/dispute/resolve', {
      asset_id: assetId,
      remedy: resolveRemedy,
      details: resolveDetails,
    });
    if (res.success && res.data?.ok) {
      showToast(_['resolve-success'], 'success');
      setResolveId(null);
      setResolveRemedy('');
      setResolveDetails('');
      loadDisputes();
    } else {
      showToast(res.error || res.data?.error || _['error-generic'], 'error');
    }
    setResolving(false);
  };

  const onSubmitEvidence = async (disputeId: string) => {
    if (!evidenceHash || !evidenceType) return;
    setSubmittingEvidence(true);
    const res = await post<{ ok: boolean; error?: string }>('/evidence/submit', {
      dispute_id: disputeId,
      submitter: walletAddress(),
      evidence_hash: evidenceHash,
      evidence_type: evidenceType,
      description: evidenceDesc,
    });
    if (res.success && res.data?.ok) {
      showToast(_['evidence-success'], 'success');
      setEvidenceId(null);
      setEvidenceHash('');
      setEvidenceType('');
      setEvidenceDesc('');
      loadDisputes();
    } else {
      showToast(res.error || res.data?.error || _['error-generic'], 'error');
    }
    setSubmittingEvidence(false);
  };

  return (
    <div class="my-disputes">
      <h3 class="label-inline mb-12">{_['my-disputes']}</h3>
      {loading ? (
        <div class="skeleton skeleton-md mb-8" role="status" aria-busy="true" aria-label={_['loading']} />
      ) : disputes.length === 0 ? (
        <div class="caption fg-muted">
          <div class="mb-4">{_['dispute-no-disputes']}</div>
          <div>{_['dispute-no-disputes-hint']}</div>
        </div>
      ) : (
        <div class="dispute-list">
          {disputes.map(d => (
            <div key={d.dispute_id} class="dispute-item">
              <div class="dispute-item-header">
                <span class="mono">{maskIdShort(d.asset_id)}</span>
                <span class={`dispute-status dispute-status-${d.status}`}>{statusLabel(d.status)}</span>
              </div>
              <div class="dispute-item-reason">{d.reason}</div>
              <div class="kv">
                <span class="kv-key">{_['dispute-created']}</span>
                <span class="kv-val">{fmtDate(d.created_at)}</span>
              </div>
              {d.resolved_at && (
                <div class="kv">
                  <span class="kv-key">{_['dispute-resolved-at']}</span>
                  <span class="kv-val">{fmtDate(d.resolved_at)}</span>
                </div>
              )}
              {d.resolution && (
                <div class="kv">
                  <span class="kv-key">{_['dispute-resolution']}</span>
                  <span class="kv-val">{d.resolution}</span>
                </div>
              )}
              {d.evidence_text && (
                <div class="kv">
                  <span class="kv-key">{_['dispute-evidence']}</span>
                  <span class="kv-val">{d.evidence_text}</span>
                </div>
              )}

              {d.status === 'open' && (
                <>
                  {/* Action buttons */}
                  <div class="row gap-8 mt-8">
                    <button
                      class="btn btn-sm btn-ghost"
                      onClick={() => setVotingId(votingId === d.dispute_id ? null : d.dispute_id)}
                    >
                      {_['jury-vote']}
                    </button>
                    <button
                      class="btn btn-sm btn-ghost"
                      onClick={() => setEvidenceId(evidenceId === d.dispute_id ? null : d.dispute_id)}
                    >
                      {_['submit-evidence']}
                    </button>
                    <button
                      class="btn btn-sm btn-ghost"
                      onClick={() => setResolveId(resolveId === d.dispute_id ? null : d.dispute_id)}
                    >
                      {_['resolve-dispute']}
                    </button>
                  </div>

                  {/* Jury vote form */}
                  {votingId === d.dispute_id && (
                    <div class="col gap-8 mt-8">
                      <span class="caption">{_['jury-verdict']}</span>
                      <div class="row gap-8">
                        <button
                          class="btn btn-sm btn-ghost grow"
                          disabled={voting}
                          onClick={() => onJuryVote(d.dispute_id, 'uphold')}
                        >
                          {voting ? _['jury-voting'] : _['jury-uphold']}
                        </button>
                        <button
                          class="btn btn-sm btn-ghost grow"
                          disabled={voting}
                          onClick={() => onJuryVote(d.dispute_id, 'reject')}
                        >
                          {voting ? _['jury-voting'] : _['jury-reject']}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Evidence submission form */}
                  {evidenceId === d.dispute_id && (
                    <div class="col gap-8 mt-8">
                      <span class="caption">{_['evidence-hash']}</span>
                      <input
                        class="input"
                        value={evidenceHash}
                        onInput={e => setEvidenceHash((e.target as HTMLInputElement).value)}
                      />
                      <span class="caption">{_['evidence-type']}</span>
                      <select
                        class="input"
                        value={evidenceType}
                        onChange={e => setEvidenceType((e.target as HTMLSelectElement).value)}
                      >
                        <option value="">{_['evidence-type']}</option>
                        {EVIDENCE_TYPES.map(t => (
                          <option key={t} value={t}>{_[`evidence-type-${t}`]}</option>
                        ))}
                      </select>
                      <span class="caption">{_['evidence-desc']}</span>
                      <textarea
                        class="input input-textarea"
                        value={evidenceDesc}
                        onInput={e => setEvidenceDesc((e.target as HTMLTextAreaElement).value)}
                        rows={3}
                      />
                      <button
                        class="btn btn-sm btn-primary"
                        disabled={submittingEvidence}
                        onClick={() => onSubmitEvidence(d.dispute_id)}
                      >
                        {submittingEvidence ? _['submitting-evidence'] : _['submit-evidence']}
                      </button>
                    </div>
                  )}

                  {/* Resolve dispute form */}
                  {resolveId === d.dispute_id && (
                    <div class="col gap-8 mt-8">
                      <span class="caption">{_['resolve-remedy']}</span>
                      <select
                        class="input"
                        value={resolveRemedy}
                        onChange={e => setResolveRemedy((e.target as HTMLSelectElement).value)}
                      >
                        <option value="">{_['resolve-remedy']}</option>
                        {REMEDIES.map(r => (
                          <option key={r} value={r}>{_[`remedy-${r}`]}</option>
                        ))}
                      </select>
                      <span class="caption">{_['resolve-details']}</span>
                      <textarea
                        class="input input-textarea"
                        value={resolveDetails}
                        onInput={e => setResolveDetails((e.target as HTMLTextAreaElement).value)}
                        rows={3}
                      />
                      <button
                        class="btn btn-sm btn-primary"
                        disabled={resolving}
                        onClick={() => onResolve(d.asset_id)}
                      >
                        {resolving ? _['resolving'] : _['resolve-dispute']}
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
