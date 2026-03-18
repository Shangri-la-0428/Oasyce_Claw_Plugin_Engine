/**
 * MyData — 我的数据
 */
import { useEffect, useState } from 'preact/hooks';
import { get, post } from '../api/client';
import { assets, loadAssets, deleteAsset } from '../store/assets';
// scanDirectory/lastScan/scanning available from '../store/scanner' if needed
import { showToast, i18n } from '../store/ui';
import { maskIdShort, maskIdLong, maskOwner, fmtPrice, safePct } from '../utils';
import RegisterForm from '../components/register-form';
import './mydata.css';

const RIGHTS_BADGE_CLASS: Record<string, string> = {
  original: 'badge-green',
  co_creation: 'badge-blue',
  licensed: 'badge-yellow',
  collection: '',
};

type SortBy = 'time' | 'value';
type MyDataTab = 'data' | 'caps';

interface DeliveryEndpoint {
  capability_id: string;
  name: string;
  endpoint: string;
  price: number;
  total_calls: number;
  success_rate: number;
  avg_latency_ms: number;
  tags?: string[];
}

interface EarningsData {
  total_earned: number;
  total_calls: number;
  recent?: { capability_id: string; amount: number; timestamp: number }[];
}

export default function MyData() {
  const [q, setQ] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [sortBy, setSortBy] = useState<SortBy>('time');
  const [tagFilter, setTagFilter] = useState<string | null>(null);

  const [reregistering, setReregistering] = useState<string | null>(null);
  const [disputeTarget, setDisputeTarget] = useState<string | null>(null);
  const [disputeReason, setDisputeReason] = useState('');
  const [disputing, setDisputing] = useState(false);

  // Tab state
  const [activeTab, setActiveTab] = useState<MyDataTab>('data');

  // My Capabilities state
  const [myCaps, setMyCaps] = useState<DeliveryEndpoint[]>([]);
  const [myCapsLoading, setMyCapsLoading] = useState(false);
  const [earnings, setEarnings] = useState<EarningsData | null>(null);

  const _ = i18n.value;

  const loadMyCaps = async () => {
    setMyCapsLoading(true);
    const res = await get<DeliveryEndpoint[]>('/delivery/endpoints?provider=gui_user');
    if (res.success && Array.isArray(res.data)) setMyCaps(res.data);
    const eres = await get<EarningsData>('/delivery/earnings?provider=gui_user');
    if (eres.success && eres.data && typeof eres.data === 'object') setEarnings(eres.data);
    setMyCapsLoading(false);
  };

  useEffect(() => { loadAssets(); loadMyCaps(); }, []);

  const handleRegisterSuccess = () => {
    loadAssets();
  };

  const allTags = [...new Set(assets.value.flatMap(a => a.tags ?? []))];

  const filtered = assets.value.filter(a => {
    if (tagFilter && !(a.tags ?? []).includes(tagFilter)) return false;
    if (!q) return true;
    const s = q.toLowerCase();
    return a.asset_id.toLowerCase().includes(s)
      || a.owner?.toLowerCase().includes(s)
      || a.tags?.some(tag => tag.toLowerCase().includes(s));
  });

  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'value') return (b.spot_price ?? 0) - (a.spot_price ?? 0);
    return (b.created_at ?? 0) - (a.created_at ?? 0);
  });

  const list = sorted.slice(0, pageSize);
  const hasMore = sorted.length > pageSize;

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showToast(_['copied'], 'success');
    } catch {
      showToast(_['error-generic'], 'error');
    }
  };

  const onDelete = async (id: string) => {
    setDeleting(true);
    const res = await deleteAsset(id);
    if (res.success) { showToast(_['removed'], 'success'); loadAssets(); }
    else showToast(res.error || _['error-generic'], 'error');
    setConfirmDel(null); setDeleting(false);
  };

  const onReRegister = async (id: string) => {
    setReregistering(id);
    const res = await post<{ ok?: boolean; version?: number; message?: string }>('/re-register', { asset_id: id });
    if (res.success && res.data?.ok) {
      showToast(`v${res.data.version}`, 'success');
      loadAssets();
    } else {
      showToast(res.data?.message || res.error || _['error-generic'], 'error');
    }
    setReregistering(null);
  };

  const onDispute = async (assetId: string) => {
    if (!disputeReason.trim()) return;
    setDisputing(true);
    const res = await post<{ ok?: boolean }>('/dispute', { asset_id: assetId, reason: disputeReason.trim() });
    if (res.success && res.data?.ok) {
      showToast(_['dispute-success'] || 'Dispute submitted', 'success');
      loadAssets();
      setDisputeTarget(null); setDisputeReason('');
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setDisputing(false);
  };

  return (
    <div class="page">
      {/* Label 标题 + 计数 */}
      <div class="row between mb-24">
        <h1 class="label m-0">{_['mydata']}</h1>
        <span class="mono fg-muted">{activeTab === 'data' ? assets.value.length : myCaps.length}</span>
      </div>

      {/* Tab switcher */}
      <div class="tabs mb-24">
        <button class={`tab ${activeTab === 'data' ? 'active' : ''}`} onClick={() => setActiveTab('data')}>
          {_['my-data-tab']}
        </button>
        <button class={`tab ${activeTab === 'caps' ? 'active' : ''}`} onClick={() => setActiveTab('caps')}>
          {_['my-caps']}
          {myCaps.length > 0 && <span class="tab-count">{myCaps.length}</span>}
        </button>
      </div>

      {activeTab === 'data' && <>
      {/* ── 注册区 ── */}
      <div class="mb-24">
        <RegisterForm mode="data" onSuccess={handleRegisterSuccess} compact />
      </div>

      {/* 搜索框 + 排序按钮 */}
      {assets.value.length > 0 && (
        <div class="row gap-8 mb-24">
          <div class="search-box-wrap">
            <input class="search-box" value={q} onInput={e => setQ((e.target as HTMLInputElement).value)} placeholder={_['search']} />
          </div>
          <button class={`btn btn-sm ${sortBy === 'time' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('time')}>{_['sort-time']}</button>
          <button class={`btn btn-sm ${sortBy === 'value' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('value')}>{_['sort-value']}</button>
        </div>
      )}

      {/* Tag 过滤 */}
      {allTags.length > 0 && (
        <div class="tag-chips mb-24">
          <button class={`tag-chip ${tagFilter === null ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(null)}>{_['all']}</button>
          {allTags.map(tag => (
            <button key={tag} class={`tag-chip ${tagFilter === tag ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(tagFilter === tag ? null : tag)}>{tag}</button>
          ))}
        </div>
      )}

      {/* 数据列表 */}
      {list.length === 0 ? (
        <div class="center p-0-64">
          <div class="empty-text mb-8">{q ? _['inbox-no-match'] : _['no-data']}</div>
          {!q && <div class="caption">{_['first-data']}</div>}
        </div>
      ) : (
        <div class="item-list">
          {list.map(a => {
            const isOpen = expanded === a.asset_id;
            const isDel = confirmDel === a.asset_id;
            return (
              <div key={a.asset_id} class="data-item">
                <button type="button" class="item-row" aria-expanded={isOpen} onClick={() => setExpanded(isOpen ? null : a.asset_id)}>
                  <div class="grow">
                    <div class="item-name">
                      {a.tags?.length ? a.tags.join(' · ') : maskIdShort(a.asset_id)}
                      {a.rights_type && (
                        <span class={`badge ml-8 ${RIGHTS_BADGE_CLASS[a.rights_type] || ''}`}>
                          {_[`rights-${a.rights_type}`] || a.rights_type}
                        </span>
                      )}
                      {a.disputed && (
                        <span class="badge badge-red ml-8">{_['disputed']}</span>
                      )}
                      {a.hash_status === 'changed' && <>
                        <span class="badge badge-yellow ml-8">{_['hash-changed']}</span>
                        <button class="btn btn-sm btn-ghost btn-reregister" disabled={reregistering === a.asset_id} onClick={e => { e.stopPropagation(); onReRegister(a.asset_id); }}>
                          {reregistering === a.asset_id ? '…' : _['re-register']}
                        </button>
                      </>}
                      {a.hash_status === 'missing' && <span class="badge badge-red ml-8">{_['file-missing']}</span>}
                    </div>
                    <div class="item-meta">
                      <span class="mono data-id-inline">{maskIdShort(a.asset_id)}</span>
                      {a.owner && <span class="data-owner-inline">{maskOwner(a.owner)}</span>}
                    </div>
                  </div>
                  <span class="mono item-price">{fmtPrice(a.spot_price)} <span class="oas-unit">OAS</span></span>
                  <span class={`data-chevron ${isOpen ? 'open' : ''}`}>›</span>
                </button>

                {/* 展开详情缩进 16px */}
                {isOpen && (
                  <div class="data-detail">
                    <div class="kv">
                      <span class="kv-key">{_['id']}</span>
                      <span class="kv-val">
                        <span class="masked">
                          <span>{maskIdLong(a.asset_id)}</span>
                          <button class="btn-copy" onClick={() => copyText(a.asset_id)}>{_['copy']}</button>
                        </span>
                      </span>
                    </div>
                    <div class="kv">
                      <span class="kv-key">{_['owner']}</span>
                      <span class="kv-val">
                        <span class="masked">
                          <span>{maskOwner(a.owner || '')}</span>
                          <button class="btn-copy" onClick={() => copyText(a.owner || '')}>{_['copy']}</button>
                        </span>
                      </span>
                    </div>
                    <div class="kv"><span class="kv-key">{_['value']}</span><span class="kv-val">{fmtPrice(a.spot_price)}</span></div>
                    {a.rights_type && (
                      <div class="kv"><span class="kv-key">{_['rights-type']}</span><span class="kv-val">{_[`rights-${a.rights_type}`] || a.rights_type}</span></div>
                    )}
                    {(a as any).price_model === 'fixed' && (
                      <div class="kv"><span class="kv-key">{_['price-model']}</span><span class="kv-val">{_['price-model-fixed']}: <span class="mono">{(a as any).price ?? '—'} OAS</span></span></div>
                    )}
                    {(a as any).price_model === 'floor' && (
                      <div class="kv"><span class="kv-key">{_['price-model']}</span><span class="kv-val">{_['price-model-floor']}: <span class="mono">{(a as any).price ?? '—'} OAS</span></span></div>
                    )}
                    {a.co_creators && a.co_creators.length > 0 && (
                      <div class="cocreator-list">
                        <span class="kv-key">{_['co-creators']}</span>
                        <div class="cocreator-list-inner">
                          {a.co_creators.map((c: any, i: number) => (
                            <div key={i} class="caption cocreator-item">
                              {c.address || '—'} <span class="mono">{c.share}%</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Delisted badge */}
                    {a.delisted && (
                      <div class="caption mt-8 block-alert">
                        {_['delisted']}
                      </div>
                    )}

                    {/* Dispute section */}
                    {a.disputed && (
                      <div class="dispute-box block-dispute">
                        <div class="caption color-red mb-4">
                          {_['dispute-status']}:{' '}
                          {a.dispute_status === 'resolved'
                            ? _['dispute-resolved']
                            : a.dispute_status === 'dismissed'
                              ? _['dispute-dismissed']
                              : _['dispute-pending']}
                        </div>
                        {a.dispute_reason && (
                          <div class="caption mb-4">{_['dispute-reason']}: {a.dispute_reason}</div>
                        )}
                        {a.dispute_resolution && (
                          <div class="caption mb-4 color-green">
                            {_[`remedy-${a.dispute_resolution.remedy}`] || a.dispute_resolution.remedy}
                          </div>
                        )}
                        {a.dispute_status === 'open' && a.arbitrator_candidates && a.arbitrator_candidates.length > 0 && (
                          <div class="dispute-arb-wrap">
                            <div class="caption fw-600 mb-4">{_['arbitrators']}</div>
                            {a.arbitrator_candidates.map((arb: any, i: number) => (
                              <div key={i} class="caption dispute-arb-item">
                                {arb.name || (arb.capability_id ? arb.capability_id.slice(0, 8) + '...' : '--')}
                                <span class="mono ml-8 fg-muted">{_['arbitrator-score']}: {safePct(arb.score, 0)}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {a.dispute_status === 'open' && (!a.arbitrator_candidates || a.arbitrator_candidates.length === 0) && (
                          <div class="caption fg-muted">{_['no-arbitrators']}</div>
                        )}
                      </div>
                    )}
                    {!a.disputed && disputeTarget !== a.asset_id && (
                      <button class="btn btn-ghost btn-sm mt-8" onClick={e => { e.stopPropagation(); setDisputeTarget(a.asset_id); setDisputeReason(''); }}>
                        {_['dispute']}
                      </button>
                    )}
                    {disputeTarget === a.asset_id && (
                      <div class="dispute-box">
                        <input class="input mb-6" value={disputeReason}
                          onInput={e => setDisputeReason((e.target as HTMLInputElement).value)}
                          placeholder={_['dispute-reason-hint']} />
                        <div class="caption mb-6 fg-muted">{_['arbitrator-auto']}</div>
                        <div class="row gap-8">
                          <button class="btn btn-ghost btn-sm" onClick={() => { setDisputeTarget(null); setDisputeReason(''); }}>{_['cancel']}</button>
                          <button class="btn btn-danger btn-sm" onClick={() => onDispute(a.asset_id)} disabled={disputing || !disputeReason.trim()}>
                            {disputing ? (_['dispute-submitting']) : (_['dispute-confirm'])}
                          </button>
                        </div>
                      </div>
                    )}

                    {!isDel ? (
                      <button class="btn btn-danger mt-12" onClick={e => { e.stopPropagation(); setConfirmDel(a.asset_id); }}>{_['delete']}</button>
                    ) : (
                      <div class="data-del-confirm">
                        <span class="caption">{_['delete-confirm']}</span>
                        <div class="row gap-8">
                          <button class="btn btn-ghost btn-sm" onClick={() => setConfirmDel(null)}>{_['cancel']}</button>
                          <button class="btn btn-danger btn-sm" onClick={() => onDelete(a.asset_id)} disabled={deleting}>
                            {deleting ? '…' : _['confirm-remove']}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 加载更多 / 没有更多 */}
      {list.length > 0 && (
        <div class="center p-0-24">
          {hasMore ? (
            <button class="btn btn-ghost btn-sm" onClick={() => setPageSize(s => s + 20)}>{_['load-more']}</button>
          ) : (
            <span class="caption">{_['no-more']}</span>
          )}
        </div>
      )}
      </>}

      {/* ── My Capabilities Tab ── */}
      {activeTab === 'caps' && <>
        {myCapsLoading ? (
          <div>
            <div class="skeleton skeleton-sm mb-8" />
            <div class="skeleton skeleton-sm mb-8" />
          </div>
        ) : myCaps.length === 0 ? (
          <div class="center p-0-64">
            <div class="empty-text mb-8">{_['cap-no-caps']}</div>
            <div class="caption">{_['cap-no-caps-hint']}</div>
          </div>
        ) : (
          <div class="item-list">
            {myCaps.map(cap => (
              <div key={cap.capability_id} class="data-item">
                <div class="item-row cursor-default">
                  <div class="grow">
                    <div class="item-name">
                      <span class="type-badge cap-badge">⚡</span>
                      {cap.name || maskIdShort(cap.capability_id)}
                    </div>
                    <div class="item-meta">
                      <span class="mono data-id-inline">{maskIdShort(cap.capability_id)}</span>
                      <span class="caption ml-8">{_['cap-endpoint-url']}: {cap.endpoint ? cap.endpoint.replace(/^(https?:\/\/[^/]+).*/, '$1/•••') : '—'}</span>
                    </div>
                  </div>
                  <span class="mono item-price">{cap.price ?? 0} <span class="oas-unit">OAS</span></span>
                </div>
                <div class="cap-detail-pad">
                  <div class="row gap-16 wrap">
                    <div class="kv"><span class="kv-key">{_['cap-total-calls']}</span><span class="kv-val">{cap.total_calls ?? 0}</span></div>
                    <div class="kv"><span class="kv-key">{_['cap-success-rate']}</span><span class="kv-val">{safePct(cap.success_rate)}</span></div>
                    <div class="kv"><span class="kv-key">{_['cap-avg-latency']}</span><span class="kv-val">{cap.avg_latency_ms != null && Number.isFinite(cap.avg_latency_ms) ? cap.avg_latency_ms.toFixed(0) + ' ms' : '--'}</span></div>
                  </div>
                  {cap.tags && cap.tags.length > 0 && (
                    <div class="tag-chips mt-8">
                      {cap.tags.map(tag => <span key={tag} class="tag-chip">{tag}</span>)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Earnings section */}
        {earnings && (
          <div class="mt-24">
            <h2 class="label-inline mb-12">{_['cap-earnings']}</h2>
            <div class="row gap-16 wrap">
              <div class="kv"><span class="kv-key">{_['cap-total-earned']}</span><span class="kv-val">{fmtPrice(earnings.total_earned)} OAS</span></div>
              <div class="kv"><span class="kv-key">{_['cap-total-calls']}</span><span class="kv-val">{earnings.total_calls ?? 0}</span></div>
            </div>
          </div>
        )}
      </>}
    </div>
  );
}
