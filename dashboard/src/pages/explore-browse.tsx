/**
 * Browse tab — search, type/tag filtering, asset list, quote/buy flow, capability invoke
 */
import { useEffect, useState, useRef, useMemo } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n } from '../store/ui';
import type { Asset } from '../store/assets';
import { maskIdShort, maskIdLong, maskOwner, fmtPrice, safePct, safeNum } from '../utils';
import './explore.css';

type AssetFilter = 'all' | 'data' | 'capability';
type SortBy = 'time' | 'value';
type BuyStep = 'form' | 'quoted' | 'success';

interface QuoteData {
  spot_price: number;
  total_cost: number;
  shares_received: number;
  price_impact: number;
  fee_breakdown?: { creator?: number; protocol?: number; router?: number };
}

interface BuyResult {
  success: boolean;
  shares: number;
  cost: number;
  new_price: number;
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
  const [buyAmt, setBuyAmt] = useState('10');
  const [buyStep, setBuyStep] = useState<BuyStep>('form');
  const [quote, setQuote] = useState<QuoteData | null>(null);
  const [buyResult, setBuyResult] = useState<BuyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [invokeResult, setInvokeResult] = useState<any>(null);
  const [invokeInput, setInvokeInput] = useState('{"text": "hello"}');
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
    setQuote(null);
    setBuyResult(null);
    setBuyStep('form');
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
      return (b.created_at ?? 0) - (a.created_at ?? 0);
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

  /* 报价 — uses POST /api/quote */
  const onQuote = async (assetId: string) => {
    setLoading(true);
    const res = await post<QuoteData>('/quote', { asset_id: assetId, amount: parseFloat(buyAmt) });
    if (res.success && res.data) {
      setQuote(res.data);
      setBuyStep('quoted');
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  /* 购买 — uses POST /api/buy */
  const onBuy = async (assetId: string) => {
    setLoading(true);
    const res = await post<BuyResult>('/buy', { asset_id: assetId, buyer_id: 'gui_user', amount: parseFloat(buyAmt) });
    if (res.success && res.data) {
      setBuyResult(res.data);
      setBuyStep('success');
      showToast(_['buy-success'], 'success');
      // Refresh assets
      const r = await get<Asset[]>('/assets');
      if (r.success && r.data) {
        const dataAssets = r.data.map(a => ({ ...a, asset_type: 'data' as const }));
        setAllAssets(prev => [...dataAssets, ...prev.filter(a => a.asset_type === 'capability')]);
      }
    } else {
      showToast(res.error || _['error-generic'], 'error');
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
      consumer: 'gui_user',
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
      setBuyAmt('10');
    } else {
      setActiveId(id);
      setQuote(null);
      setBuyResult(null);
      setBuyStep('form');
      setInvokeResult(null);
      setBuyAmt('10');
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
                          {(a as any).total_calls != null && (
                            <div class="row gap-16 wrap">
                              <div class="kv"><span class="kv-key">{_['cap-total-calls']}</span><span class="kv-val">{(a as any).total_calls}</span></div>
                              {(a as any).success_rate != null && <div class="kv"><span class="kv-key">{_['cap-success-rate']}</span><span class="kv-val">{safePct((a as any).success_rate)}</span></div>}
                              {(a as any).avg_latency_ms != null && <div class="kv"><span class="kv-key">{_['cap-avg-latency']}</span><span class="kv-val">{safeNum((a as any).avg_latency_ms, 0)} ms</span></div>}
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
                      /* ── Data asset buy flow ── */
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

                          {/* Amount input */}
                          <div>
                            <label class="label">{_['amount']}</label>
                            <input class="input" type="number" value={buyAmt} onInput={e => setBuyAmt((e.target as HTMLInputElement).value)} min="1" />
                          </div>
                          <button class="btn btn-primary btn-full" onClick={() => onQuote(a.asset_id)} disabled={loading}>
                            {loading ? _['quoting'] : _['quote']}
                          </button>
                        </div>
                      ) : buyStep === 'quoted' && quote ? (
                        <div class="col gap-8">
                          {/* Quote details */}
                          <div class="kv"><span class="kv-key">{_['spot-price']}</span><span class="kv-val">{fmtPrice(quote.spot_price)} OAS</span></div>
                          <div class="kv"><span class="kv-key">{_['total-cost']}</span><span class="kv-val">{fmtPrice(quote.total_cost)} OAS</span></div>
                          <div class="kv"><span class="kv-key">{_['shares-received']}</span><span class="kv-val">{quote.shares_received}</span></div>
                          {(a as any).price_model !== 'fixed' && (
                            <div class="kv"><span class="kv-key">{_['price-impact']}</span><span class="kv-val">{quote.price_impact}%</span></div>
                          )}
                          {quote.fee_breakdown && (
                            <div class="quote-fees">
                              <div class="label">{_['fees']}</div>
                              {quote.fee_breakdown.creator != null && <div class="kv"><span class="kv-key">{_['creator-fee']}</span><span class="kv-val">{fmtPrice(quote.fee_breakdown.creator)} OAS</span></div>}
                              {quote.fee_breakdown.protocol != null && <div class="kv"><span class="kv-key">{_['protocol-fee']}</span><span class="kv-val">{fmtPrice(quote.fee_breakdown.protocol)} OAS</span></div>}
                              {quote.fee_breakdown.router != null && <div class="kv"><span class="kv-key">{_['router-fee']}</span><span class="kv-val">{fmtPrice(quote.fee_breakdown.router)} OAS</span></div>}
                            </div>
                          )}
                          <div class="row gap-16 mt-24">
                            <button class="btn btn-ghost grow" onClick={() => { setQuote(null); setBuyStep('form'); }}>{_['back']}</button>
                            <button class="btn btn-primary grow" onClick={() => onBuy(a.asset_id)} disabled={loading}>
                              {loading ? _['buying'] : _['confirm-buy']}
                            </button>
                          </div>
                        </div>
                      ) : buyStep === 'success' && buyResult ? (
                        <div class="col gap-8">
                          <div class="buy-success-banner">{_['buy-success']}</div>
                          <div class="kv"><span class="kv-key">{_['shares-bought']}</span><span class="kv-val">{buyResult.shares}</span></div>
                          <div class="kv"><span class="kv-key">{_['pay']}</span><span class="kv-val">{fmtPrice(buyResult.cost)} OAS</span></div>
                          <div class="kv"><span class="kv-key">{_['new-price']}</span><span class="kv-val">{fmtPrice(buyResult.new_price)} OAS</span></div>
                          <button class="btn btn-ghost btn-full mt-16" onClick={() => { resetActive(); setBuyAmt('10'); }}>{_['back']}</button>
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
    </>
  );
}
