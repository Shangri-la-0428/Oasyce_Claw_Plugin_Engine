/**
 * Earnings tab — Provider earnings stats + invocation history
 * PRD: docs/PRD-capability-sell.md Feature 1 & 2
 */
import { useEffect, useState } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n, walletAddress } from '../store/ui';
import { maskIdShort, fmtPrice, fmtDate, copyText } from '../utils';
import { EmptyState } from '../components/empty-state';
import './explore.css';

interface Earnings {
  provider_id: string;
  total_earnings: number;
  invocations: number;
}

interface Invocation {
  invocation_id: string;
  capability_id: string;
  price: number;
  status: string;
  timestamp: number;
}

interface Props {
  onRegister?: () => void;
}

export default function ExploreEarnings({ onRegister }: Props) {
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  const [invocations, setInvocations] = useState<Invocation[]>([]);
  const [earningsLoading, setEarningsLoading] = useState(true);
  const [invLoading, setInvLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const _ = i18n.value;
  const addr = walletAddress();

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setEarningsLoading(true);
      const res = await get<Earnings>(`/delivery/earnings?provider=${addr}`);
      if (!cancelled) {
        if (res.success && res.data) setEarnings(res.data);
        setEarningsLoading(false);
      }

      setInvLoading(true);
      const invRes = await get<Invocation[]>(`/delivery/invocations?provider=${addr}&limit=20`);
      if (!cancelled) {
        if (invRes.success && Array.isArray(invRes.data)) setInvocations(invRes.data);
        setInvLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [addr]);

  const reload = async () => {
    const invRes = await get<Invocation[]>(`/delivery/invocations?provider=${addr}&limit=20`);
    if (invRes.success && Array.isArray(invRes.data)) setInvocations(invRes.data);
    const res = await get<Earnings>(`/delivery/earnings?provider=${addr}`);
    if (res.success && res.data) setEarnings(res.data);
  };

  const onComplete = async (id: string) => {
    setActionLoading(id + '-complete');
    const res = await post(`/delivery/invocation/${id}/complete`, {});
    if (res.success) {
      showToast(_['inv-complete-success'], 'success');
      reload();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setActionLoading(null);
  };

  const onClaim = async (id: string) => {
    setActionLoading(id + '-claim');
    const res = await post(`/delivery/invocation/${id}/claim`, {});
    if (res.success) {
      showToast(_['inv-claim-success'], 'success');
      reload();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setActionLoading(null);
  };

  const isEmpty = !earningsLoading && (!earnings || (earnings.total_earnings === 0 && earnings.invocations === 0));

  return (
    <>
      {/* ── Stats ── */}
      <div class="earnings-stats">
        {earningsLoading ? (
          <>
            <div class="skeleton skeleton-md" role="status" aria-busy="true" aria-label={_['loading']} />
            <div class="skeleton skeleton-sm" role="status" aria-busy="true" />
          </>
        ) : isEmpty ? (
          <EmptyState icon="⟐" title={_['earnings-empty']} hint="">
            {onRegister && (
              <button class="btn btn-ghost mt-16" onClick={onRegister}>
                {_['earnings-empty-cta']}
              </button>
            )}
          </EmptyState>
        ) : (
          <>
            <div class="earnings-stat-row">
              <div class="earnings-stat">
                <span class="earnings-stat-label">{_['total-earnings']}</span>
                <span class="earnings-stat-val mono">{fmtPrice(earnings!.total_earnings)} <span class="earnings-unit">OAS</span></span>
              </div>
              <div class="earnings-stat">
                <span class="earnings-stat-label">{_['total-invocations']}</span>
                <span class="earnings-stat-val mono">{earnings!.invocations}</span>
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── Invocation History ── */}
      {!isEmpty && (
        <div class="mt-32">
          <h2 class="label-inline mb-16">{_['invocation-history']}</h2>
          {invLoading ? (
            <div class="col gap-8">
              {[0, 1, 2].map(i => (
                <div key={i} class="skeleton skeleton-md" role="status" aria-busy="true" />
              ))}
            </div>
          ) : invocations.length === 0 ? (
            <EmptyState icon="⇄" title={_['invocation-empty']} />
          ) : (
            <div class="inv-list">
              {invocations.map(inv => (
                <div
                  key={inv.invocation_id}
                  class={`inv-item ${expandedId === inv.invocation_id ? 'inv-item-expanded' : ''}`}
                  onClick={() => setExpandedId(expandedId === inv.invocation_id ? null : inv.invocation_id)}
                >
                  <div class="inv-item-main">
                    <span class="mono inv-cap-id">{maskIdShort(inv.capability_id)}</span>
                    <span class={`inv-status inv-status-${inv.status}`}>{inv.status}</span>
                    <span class="mono inv-price">{fmtPrice(inv.price)} OAS</span>
                    <span class="caption fg-muted inv-time">{fmtDate(inv.timestamp, 'datetime')}</span>
                  </div>
                  {expandedId === inv.invocation_id && (
                    <div class="inv-detail">
                      <div class="kv">
                        <span class="kv-key">ID</span>
                        <button
                          class="kv-val mono btn-link"
                          onClick={e => { e.stopPropagation(); copyText(inv.invocation_id); }}
                          title={inv.invocation_id}
                        >
                          {maskIdShort(inv.invocation_id)}
                        </button>
                      </div>
                      <div class="kv">
                        <span class="kv-key">Capability</span>
                        <button
                          class="kv-val mono btn-link"
                          onClick={e => { e.stopPropagation(); copyText(inv.capability_id); }}
                          title={inv.capability_id}
                        >
                          {maskIdShort(inv.capability_id)}
                        </button>
                      </div>
                      {/* Provider actions based on invocation status */}
                      {inv.status === 'pending' && (
                        <div class="row gap-8 mt-8">
                          <button
                            class="btn btn-sm btn-ghost"
                            disabled={actionLoading === inv.invocation_id + '-complete'}
                            onClick={e => { e.stopPropagation(); onComplete(inv.invocation_id); }}
                          >
                            {actionLoading === inv.invocation_id + '-complete' ? _['inv-completing'] : _['inv-complete']}
                          </button>
                        </div>
                      )}
                      {inv.status === 'completed' && (
                        <div class="row gap-8 mt-8">
                          <button
                            class="btn btn-sm btn-ghost"
                            disabled={actionLoading === inv.invocation_id + '-claim'}
                            onClick={e => { e.stopPropagation(); onClaim(inv.invocation_id); }}
                          >
                            {actionLoading === inv.invocation_id + '-claim' ? _['inv-claiming'] : _['inv-claim']}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
