/**
 * Global Disputes tab — all disputes across the network
 */
import { useEffect, useState } from 'preact/hooks';
import { get } from '../api/client';
import { i18n } from '../store/ui';
import { maskIdShort, fmtDate, copyText } from '../utils';
import { EmptyState } from '../components/empty-state';
import './explore.css';

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

type StatusFilter = 'all' | 'open' | 'resolved' | 'dismissed';

export default function ExploreDisputes() {
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const _ = i18n.value;

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      const res = await get<{ disputes: Dispute[] }>('/disputes');
      if (!cancelled) {
        if (res.success && res.data?.disputes) {
          setDisputes(res.data.disputes);
        } else if (res.success && Array.isArray(res.data)) {
          // Handle both response shapes
          setDisputes(res.data as unknown as Dispute[]);
        }
        setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const filtered = filter === 'all' ? disputes : disputes.filter(d => d.status === filter);

  const statusFilters: StatusFilter[] = ['all', 'open', 'resolved', 'dismissed'];

  return (
    <>
      <h2 class="label-inline mb-16">{_['all-disputes']}</h2>

      {/* Status filter */}
      <div class="row gap-8 mb-24">
        {statusFilters.map(s => (
          <button
            key={s}
            class={`btn btn-sm ${filter === s ? 'btn-active' : 'btn-ghost'}`}
            onClick={() => setFilter(s)}
          >
            {s === 'all' ? _['filter-all'] : _[`dispute-${s}`] || s}
          </button>
        ))}
      </div>

      {loading ? (
        <div class="col gap-8">
          {[0, 1, 2].map(i => (
            <div key={i} class="skeleton skeleton-md" role="status" aria-busy="true" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState icon="⚖" title={_['dispute-no-global']} hint={_['dispute-no-global-hint']} />
      ) : (
        <div class="dispute-list">
          {filtered.map(d => (
            <div
              key={d.dispute_id}
              class={`dispute-item ${expandedId === d.dispute_id ? 'inv-item-expanded' : ''}`}
              onClick={() => setExpandedId(expandedId === d.dispute_id ? null : d.dispute_id)}
              style="cursor: pointer"
            >
              <div class="dispute-item-header">
                <span class="mono">{maskIdShort(d.asset_id)}</span>
                <span class={`dispute-status dispute-status-${d.status}`}>
                  {_[`dispute-${d.status}`] || d.status}
                </span>
              </div>
              <div class="dispute-item-reason">
                {_[d.reason] || d.reason}
              </div>
              {d.evidence_text && (
                <div class="dispute-item-evidence">{d.evidence_text}</div>
              )}
              <div class="dispute-item-time">{fmtDate(d.created_at, 'datetime')}</div>

              {/* Expanded details */}
              {expandedId === d.dispute_id && (
                <div class="inv-detail mt-8">
                  <div class="kv">
                    <span class="kv-key">ID</span>
                    <button
                      class="kv-val mono btn-link"
                      onClick={e => { e.stopPropagation(); copyText(d.dispute_id); }}
                      title={d.dispute_id}
                    >
                      {maskIdShort(d.dispute_id)}
                    </button>
                  </div>
                  <div class="kv">
                    <span class="kv-key">{_['dispute-buyer']}</span>
                    <button
                      class="kv-val mono btn-link"
                      onClick={e => { e.stopPropagation(); copyText(d.buyer); }}
                      title={d.buyer}
                    >
                      {maskIdShort(d.buyer)}
                    </button>
                  </div>
                  {d.resolved_at && (
                    <div class="kv">
                      <span class="kv-key">{_['dispute-resolved-at']}</span>
                      <span class="kv-val">{fmtDate(d.resolved_at, 'datetime')}</span>
                    </div>
                  )}
                  {d.resolution && (
                    <div class="kv">
                      <span class="kv-key">{_['dispute-resolution']}</span>
                      <span class="kv-val">{d.resolution}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
