/**
 * Browse tab — search, type/tag filtering, asset list, tiered access quote/buy, capability invoke
 */
import { useEffect, useState, useRef, useMemo } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n, walletAddress } from '../store/ui';
import type { Asset } from '../store/assets';
import { maskIdShort, maskIdLong, maskOwner, fmtPrice, safePct, safeNum } from '../utils';
import DataPreview from '../components/data-preview';
import './explore.css';

type AssetFilter = 'all' | 'data' | 'capability';
type SortBy = 'time' | 'value';
type BuyStep = 'form' | 'quoted' | 'success';
type AccessLevel = 'L0' | 'L1' | 'L2' | 'L3';

/** Per-level quote from /api/access/quote */
interface LevelQuote {
  level: AccessLevel;
  bond: number;
  available: boolean;
  locked_reason?: string;   // e.g. "reputation_too_low", "exceeds_max_level"
  liability_days: number;
}

/** Full quote response */
interface AccessQuoteData {
  asset_id: string;
  levels: LevelQuote[];
  reputation: number;
  max_access_level: AccessLevel;
  risk_level: string;
}

interface BuyResult {
  success: boolean;
  level: AccessLevel;
  bond: number;
  liability_days: number;
}

interface Props {
  subpath?: string;
}

export default function ExploreBrowse({ subpath }: Props) {
  const [q, setQ] = useState('');
  const [allAssets, setAllAssets] = useState<Asset[]>([]);
  const [pageSize, setPageSize] = useState(20);
  const [sortBy, setSortBy] = useState<SortBy>('time');
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<AssetFilter>('all');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<AccessLevel>('L1');
  const [buyStep, setBuyStep] = useState<BuyStep>('form');
  const [accessQuote, setAccessQuote] = useState<AccessQuoteData | null>(null);
  const [buyResult, setBuyResult] = useState<BuyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [invokeResult, setInvokeResult] = useState<any>(null);
  const [invokeInput, setInvokeInput] = useState('{"text": "hello"}');
  const [previewId, setPreviewId] = useState<string | null>(null);
  const debounceRef = useRef<number>(0);

  const _ = i18n.value;

  /* 加载数据资产 + capability 资产 */
  useEffect(() => {
    Promise.all([
      get<Asset[]>('/assets'),
      get<Asset[]>('/capabilities'),
    ]).then(([dataRes, capRes]) => {
      const rawData = dataRes.success && Array.isArray(dataRes.data) ? dataRes.data : [];
      const rawCaps = capRes.success && Array.isArray(capRes.data) ? capRes.data : [];
      const dataAssets = rawData.map(a => ({ ...a, asset_type: 'data' as const }));
      const capAssets = rawCaps.map(a => ({ ...a, asset_type: 'capability' as const }));
      setAllAssets([...dataAssets, ...capAssets]);
    }).finally(() => setInitialLoading(false));

    return () => clearTimeout(debounceRef.current);
  }, []);

  /* Close preview overlay on Escape */
  useEffect(() => {
    if (!previewId) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPreviewId(null); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [previewId]);

  /* Auto-select asset from deep link subpath (e.g. #explore/CAP_ABC123) */
  useEffect(() => {
    if (subpath && allAssets.length > 0) {
      const match = allAssets.find(a => a.asset_id === subpath);
      if (match) {
        setActiveId(match.asset_id);
      }
    }
  }, [subpath, allAssets]);

  const onSearch = (val: string) => {
    setQ(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setPageSize(20);
      resetActive();
    }, 300);
  };

  const resetActive = () => {
    setActiveId(null);
    setAccessQuote(null);
    setBuyResult(null);
    setBuyStep('form');
    setSelectedLevel('L1');
    setInvokeResult(null);
    setInvokeInput('{"text": "hello"}');
  };

  /* 过滤 + 排序 (memoized) */
  const allTags = useMemo(
    () => [...new Set(allAssets.flatMap(a => a.tags ?? []))],
    [allAssets]
  );

  const filtered = useMemo(
    () => allAssets.filter(a => {
      if (typeFilter !== 'all' && (a.asset_type || 'data') !== typeFilter) return false;
      if (tagFilter && !(a.tags ?? []).includes(tagFilter)) return false;
      if (!q) return true;
      const s = q.toLowerCase();
      return a.asset_id.toLowerCase().includes(s)
        || a.owner?.toLowerCase().includes(s)
        || a.name?.toLowerCase().includes(s)
        || a.description?.toLowerCase().includes(s)
        || a.provider?.toLowerCase().includes(s)
        || a.tags?.some(tag => tag.toLowerCase().includes(s));
    }),
    [allAssets, typeFilter, tagFilter, q]
  );

  const sorted = useMemo(
    () => [...filtered].sort((a, b) => {
      if (sortBy === 'value') return (b.spot_price ?? 0) - (a.spot_price ?? 0);
      const ta = typeof a.created_at === 'string' ? new Date(a.created_at).getTime() : (a.created_at ?? 0);
      const tb = typeof b.created_at === 'string' ? new Date(b.created_at).getTime() : (b.created_at ?? 0);
      return tb - ta;
    }),
    [filtered, sortBy]
  );

  const list = useMemo(() => sorted.slice(0, pageSize), [sorted, pageSize]);
  const hasMore = sorted.length > pageSize;

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showToast(_['copied'], 'success');
    } catch {
      showToast(_['error-generic'], 'error');
      return;
    }
  };

  /* 获取所有层级报价 — GET /api/access/quote */
  const onFetchQuote = async (assetId: string) => {
    setLoading(true);
    const buyer = walletAddress();
    const res = await get<AccessQuoteData>(
      `/access/quote?asset_id=${encodeURIComponent(assetId)}&buyer=${encodeURIComponent(buyer)}`
    );
    if (res.success && res.data) {
      setAccessQuote(res.data);
      setBuyStep('quoted');
      // Auto-select highest available level
      const available = (res.data.levels || []).filter(l => l.available);
      if (available.length > 0) {
        setSelectedLevel(available[available.length - 1].level);
      }
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  /* 购买访问权 — POST /api/access/buy */
  const onBuyAccess = async (assetId: string) => {
    setLoading(true);
    const res = await post<any>('/access/buy', {
      asset_id: assetId,
      buyer: walletAddress(),
      level: selectedLevel,
    });
    if (res.success && res.data && res.data.ok) {
      const lq = accessQuote?.levels.find(l => l.level === selectedLevel);
      setBuyResult({
        success: true,
        level: selectedLevel,
        bond: lq?.bond ?? res.data.bond ?? 0,
        liability_days: lq?.liability_days ?? res.data.liability_days ?? 0,
      });
      setBuyStep('success');
      showToast(_['buy-success'], 'success');
      // Refresh assets
      const r = await get<Asset[]>('/assets');
      if (r.success && r.data) {
        const dataAssets = r.data.map(a => ({ ...a, asset_type: 'data' as const }));
        setAllAssets(prev => [...dataAssets, ...prev.filter(a => a.asset_type === 'capability')]);
      }
    } else {
      showToast(res.data?.error || res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  /* 调用 (capability assets) — delivery protocol */
  const onInvoke = async (capId: string) => {
    setLoading(true);
    setInvokeResult(null);
    let parsedInput: any = {};
    try { parsedInput = JSON.parse(invokeInput); } catch { parsedInput = { text: invokeInput }; }
    const res = await post<any>('/delivery/invoke', {
      capability_id: capId,
      consumer: walletAddress(),
      input: parsedInput,
    });
    if (res.success && res.data?.ok) {
      setInvokeResult(res.data);
      showToast(_['invoke-success'], 'success');
    } else {
      showToast(res.data?.error || res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  const toggleItem = (id: string) => {
    if (activeId === id) {
      resetActive();
    } else {
      setActiveId(id);
      setAccessQuote(null);
      setBuyResult(null);
      setBuyStep('form');
      setSelectedLevel('L1');
      setInvokeResult(null);
    }
  };

  const isCapability = (a: Asset) => (a.asset_type || 'data') === 'capability';

  return (
    <>
      {/* Asset type filter */}
      <div class="row gap-8 mb-16">
        {(['all', 'data', 'capability'] as AssetFilter[]).map(t => (
          <button
            key={t}
            class={`btn btn-sm ${typeFilter === t ? 'btn-active' : 'btn-ghost'}`}
            onClick={() => { setTypeFilter(t); setTagFilter(null); resetActive(); }}
          >
            {_[`type-${t}`]}
          </button>
        ))}
      </div>

      {/* 搜索框 */}
      <div class="search-box-wrap mb-24">
        <input
          class="search-box"
          value={q}
          onInput={e => onSearch((e.target as HTMLInputElement).value)}
          placeholder={_['explore-search']}
        />
      </div>

      {/* Tag 过滤 + 排序 */}
      {allTags.length > 0 && (
        <div class="row between mb-24 wrap gap-12">
          <div class="tag-chips">
            <button class={`tag-chip ${tagFilter === null ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(null)}>{_['all']}</button>
            {allTags.map(tag => (
              <button key={tag} class={`tag-chip ${tagFilter === tag ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(tagFilter === tag ? null : tag)}>{tag}</button>
            ))}
          </div>
          <div class="row gap-8">
            <button class={`btn btn-sm ${sortBy === 'time' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('time')}>{_['sort-time']}</button>
            <button class={`btn btn-sm ${sortBy === 'value' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('value')}>{_['sort-value']}</button>
          </div>
        </div>
      )}

      {/* 结果列表 / 空状态 */}
      {initialLoading ? (
        <div>
          <div class="skeleton skeleton-sm mb-8" />
          <div class="skeleton skeleton-sm mb-8" />
          <div class="skeleton skeleton-sm mb-8" />
        </div>
      ) : list.length === 0 && allAssets.length === 0 ? (
        <div class="center p-0-64">
          <div class="empty-text-md mb-8">{_['explore-empty']}</div>
          <div class="caption">{_['explore-browse']}</div>
        </div>
      ) : list.length === 0 ? (
        <div class="center p-0-64">
          <div class="empty-text">{q ? _['inbox-no-match'] : _['explore-empty']}</div>
        </div>
      ) : (
        <div class="item-list">
          {list.map(a => {
            const isActive = activeId === a.asset_id;
            const isCap = isCapability(a);
            return (
              <div key={a.asset_id} class={`explore-item ${isCap ? 'explore-item-cap' : ''}`}>
                <button type="button" class="item-row" aria-expanded={isActive} onClick={() => toggleItem(a.asset_id)}>
                  <div class="grow">
                    <div class="item-name">
                      {isCap && <span class="type-badge cap-badge">⚡</span>}
                      {isCap ? (a.name || maskIdShort(a.asset_id)) : (a.tags?.length ? a.tags.join(' · ') : maskIdShort(a.asset_id))}
                      {isCap && a.version && <span class="version-tag">v{a.version}</span>}
                      {!isCap && (a as any).price_model === 'fixed' && <span class="badge ml-8">{_['price-model-fixed']}</span>}
                      {!isCap && (a as any).price_model === 'floor' && <span class="badge ml-8">{_['price-model-floor']}</span>}
                    </div>
                    <div class="item-meta">
                      <span class="mono explore-id-inline">{maskIdShort(a.asset_id)}</span>
                      {isCap && a.provider && <span class="explore-owner-inline">{maskOwner(a.provider)}</span>}
                      {!isCap && a.owner && <span class="explore-owner-inline">{maskOwner(a.owner)}</span>}
                    </div>
                  </div>
                  <span class="mono item-price">{fmtPrice(a.spot_price)} <span class="oas-unit">OAS</span></span>
                  <button class="btn btn-sm btn-ghost" onClick={(e) => { e.stopPropagation(); setPreviewId(a.asset_id); }}>{_['preview']}</button>
                  <span class="btn btn-sm btn-ghost">{isCap ? _['invoke'] : _['get-access']}</span>
                </button>

                {/* 内联操作区 */}
                {isActive && (
                  <div class="explore-inline">
                    {isCap ? (
                      /* ── Capability invoke flow (delivery protocol) ── */
                      !invokeResult ? (
                        <div class="col gap-16">
                          <div class="kv">
                            <span class="kv-key">{_['id']}</span>
                            <span class="kv-val">
                              <span class="masked">
                                <span>{maskIdLong(a.asset_id)}</span>
                                <button class="btn-copy" onClick={() => copyText(a.asset_id)}>{_['copy']}</button>
                              </span>
                            </span>
                          </div>
                          {a.description && (
                            <div class="kv">
                              <span class="kv-key">{_['describe']}</span>
                              <span class="kv-val">{a.description}</span>
                            </div>
                          )}
                          {a.total_calls != null && (
                            <div class="row gap-16 wrap">
                              <div class="kv"><span class="kv-key">{_['cap-total-calls']}</span><span class="kv-val">{a.total_calls}</span></div>
                              {a.success_rate != null && <div class="kv"><span class="kv-key">{_['cap-success-rate']}</span><span class="kv-val">{safePct(a.success_rate)}</span></div>}
                              {a.avg_latency_ms != null && <div class="kv"><span class="kv-key">{_['cap-avg-latency']}</span><span class="kv-val">{safeNum(a.avg_latency_ms, 0)} ms</span></div>}
                            </div>
                          )}
                          <div>
                            <label class="label">{_['cap-invoke-input']}</label>
                            <textarea class="input input-textarea-mono" value={invokeInput}
                              onInput={e => setInvokeInput((e.target as HTMLTextAreaElement).value)}
                              placeholder={_['cap-invoke-input-hint']} />
                          </div>
                          <button class="btn btn-primary btn-full" onClick={() => onInvoke(a.asset_id)} disabled={loading}>
                            {loading ? _['invoking'] : _['invoke']}
                          </button>
                        </div>
                      ) : (
                        <div class="col gap-8">
                          {invokeResult.price != null && <div class="kv"><span class="kv-key">{_['pay']}</span><span class="kv-val">{invokeResult.price} OAS</span></div>}
                          {invokeResult.shares_minted != null && <div class="kv"><span class="kv-key">{_['shares-minted']}</span><span class="kv-val">{invokeResult.shares_minted}</span></div>}
                          {invokeResult.result != null && (
                            <div class="kv">
                              <span class="kv-key">{_['invoke-result'] || 'Result'}</span>
                              <span class="kv-val mono invoke-result-val">{typeof invokeResult.result === 'string' ? invokeResult.result : JSON.stringify(invokeResult.result)}</span>
                            </div>
                          )}
                          <button class="btn btn-ghost btn-full" onClick={() => { setInvokeResult(null); resetActive(); }}>{_['back']}</button>
                        </div>
                      )
                    ) : (
                      /* ── Data asset: tiered access flow ── */
                      buyStep === 'form' ? (
                        <div class="col gap-16">
                          {/* Asset info */}
                          <div class="kv">
                            <span class="kv-key">{_['id']}</span>
                            <span class="kv-val">
                              <span class="masked">
                                <span>{maskIdLong(a.asset_id)}</span>
                                <button class="btn-copy" onClick={() => copyText(a.asset_id)}>{_['copy']}</button>
                              </span>
                            </span>
                          </div>
                          {a.owner && (
                            <div class="kv"><span class="kv-key">{_['owner']}</span><span class="kv-val">{maskOwner(a.owner)}</span></div>
                          )}
                          {a.tags && a.tags.length > 0 && (
                            <div class="kv"><span class="kv-key">{_['tags']}</span><span class="kv-val">{a.tags.join(', ')}</span></div>
                          )}
                          <div class="kv"><span class="kv-key">{_['type']}</span><span class="kv-val">{_['asset-type-data']}</span></div>
                          <div class="kv"><span class="kv-key">{_['spot-price']}</span><span class="kv-val">{fmtPrice(a.spot_price)} OAS</span></div>

                          <button class="btn btn-primary btn-full" onClick={() => onFetchQuote(a.asset_id)} disabled={loading}>
                            {loading ? _['quoting'] : _['quote']}
                          </button>
                        </div>
                      ) : buyStep === 'quoted' && accessQuote ? (
                        <div class="col gap-12">
                          {/* Reputation & risk context */}
                          <div class="row gap-16 wrap">
                            <div class="kv"><span class="kv-key">{_['al-reputation']}</span><span class="kv-val">{accessQuote.reputation ?? '--'}</span></div>
                            {accessQuote.risk_level && <div class="kv"><span class="kv-key">{_['al-risk']}</span><span class="kv-val badge">{accessQuote.risk_level}</span></div>}
                            {accessQuote.max_access_level && <div class="kv"><span class="kv-key">{_['al-max']}</span><span class="kv-val">{accessQuote.max_access_level}</span></div>}
                          </div>

                          {/* Access level cards */}
                          <div class="access-levels-grid">
                            {accessQuote.levels.map(lq => (
                              <button
                                key={lq.level}
                                type="button"
                                class={`access-level-card ${selectedLevel === lq.level ? 'access-level-selected' : ''} ${!lq.available ? 'access-level-locked' : ''}`}
                                onClick={() => lq.available && setSelectedLevel(lq.level)}
                                disabled={!lq.available}
                              >
                                <div class="access-level-header">
                                  <span class="access-level-name">{lq.level}</span>
                                  <span class="access-level-label">{_[`al-${lq.level}-name`]}</span>
                                </div>
                                <div class="access-level-desc">{_[`al-${lq.level}-desc`]}</div>
                                {lq.available ? (
                                  <div class="access-level-price">
                                    <span class="access-level-bond">{fmtPrice(lq.bond)}</span>
                                    <span class="oas-unit">OAS</span>
                                  </div>
                                ) : (
                                  <div class="access-level-lock-reason">{_[lq.locked_reason || 'al-locked'] || _['al-locked']}</div>
                                )}
                                {lq.available && lq.liability_days > 0 && (
                                  <div class="access-level-liability">{_['al-liability']} {lq.liability_days} {_['al-days']}</div>
                                )}
                              </button>
                            ))}
                          </div>

                          <div class="row gap-16 mt-16">
                            <button class="btn btn-ghost grow" onClick={() => { setAccessQuote(null); setBuyStep('form'); }}>{_['back']}</button>
                            <button class="btn btn-primary grow" onClick={() => onBuyAccess(a.asset_id)} disabled={loading}>
                              {loading ? _['buying'] : _['confirm-buy']}
                            </button>
                          </div>
                        </div>
                      ) : buyStep === 'success' && buyResult ? (
                        <div class="col gap-8">
                          <div class="buy-success-banner">{_['buy-success']}</div>
                          <div class="kv"><span class="kv-key">{_['al-granted']}</span><span class="kv-val">{buyResult.level}</span></div>
                          <div class="kv"><span class="kv-key">{_['al-bond-paid']}</span><span class="kv-val">{fmtPrice(buyResult.bond)} OAS</span></div>
                          {buyResult.liability_days > 0 && (
                            <div class="kv"><span class="kv-key">{_['al-liability']}</span><span class="kv-val">{buyResult.liability_days} {_['al-days']}</span></div>
                          )}
                          <button class="btn btn-ghost btn-full mt-16" onClick={() => resetActive()}>{_['back']}</button>
                        </div>
                      ) : null
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {list.length > 0 && (
        <div class="center p-0-24">
          {hasMore ? (
            <button class="btn btn-ghost btn-sm" onClick={() => setPageSize(s => s + 20)}>{_['load-more']}</button>
          ) : (
            <span class="caption">{_['no-more']}</span>
          )}
        </div>
      )}

      {/* Data Preview overlay */}
      {previewId && (
        <div class="preview-overlay" onClick={() => setPreviewId(null)}>
          <div class="preview-overlay-inner" onClick={e => e.stopPropagation()}>
            <DataPreview assetId={previewId} onClose={() => setPreviewId(null)} />
          </div>
        </div>
      )}
    </>
  );
}
