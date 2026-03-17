/**
 * Explore — 搜索网络上的资产（数据 + 服务），查看报价，获取访问权/调用
 * + Portfolio (持仓) + Stake (质押)
 */
import { useEffect, useState, useRef } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n } from '../store/ui';
import type { Asset } from '../store/assets';
import { maskIdShort, maskIdLong, maskOwner, fmtPrice } from '../utils';
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

interface Holding {
  asset_id: string;
  shares: number;
  avg_price: number;
}

interface ValidatorInfo {
  id: string;
  staked: number;
  reputation: number;
}

type ExploreTab = 'browse' | 'portfolio' | 'stake';

export default function Explore() {
  const [exploreTab, setExploreTab] = useState<ExploreTab>('browse');
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
  const debounceRef = useRef<number>(0);

  // Portfolio state
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [holdingsLoading, setHoldingsLoading] = useState(false);

  // Staking state
  const [validators, setValidators] = useState<ValidatorInfo[]>([]);
  const [stakeAmts, setStakeAmts] = useState<Record<string, string>>({});
  const [stakingId, setStakingId] = useState<string | null>(null);

  const _ = i18n.value;

  /* 加载数据资产 + capability 资产 */
  useEffect(() => {
    Promise.all([
      get<Asset[]>('/assets'),
      get<Asset[]>('/capabilities'),
    ]).then(([dataRes, capRes]) => {
      const dataAssets = (dataRes.success && dataRes.data ? dataRes.data : []).map(a => ({
        ...a, asset_type: 'data' as const,
      }));
      const capAssets = (capRes.success && capRes.data ? capRes.data : []).map(a => ({
        ...a, asset_type: 'capability' as const,
      }));
      setAllAssets([...dataAssets, ...capAssets]);
    }).finally(() => setInitialLoading(false));

    // Load portfolio
    loadPortfolio();
    // Load validators
    loadValidators();
    return () => clearTimeout(debounceRef.current);
  }, []);

  const loadPortfolio = async () => {
    setHoldingsLoading(true);
    const res = await get<Holding[]>('/shares?owner=gui_user');
    if (res.success && res.data) setHoldings(res.data);
    setHoldingsLoading(false);
  };

  const loadValidators = async () => {
    const res = await get<{ validators: ValidatorInfo[] }>('/staking');
    if (res.success && res.data?.validators) setValidators(res.data.validators);
  };

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
  };

  /* 过滤 + 排序 */
  const allTags = [...new Set(allAssets.flatMap(a => a.tags ?? []))];

  const tagCounts = allAssets.reduce<Record<string, number>>((acc, a) => {
    (a.tags ?? []).forEach(tag => { acc[tag] = (acc[tag] || 0) + 1; });
    return acc;
  }, {});

  const filtered = allAssets.filter(a => {
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
  });

  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'value') return (b.spot_price ?? 0) - (a.spot_price ?? 0);
    return (b.created_at ?? 0) - (a.created_at ?? 0);
  });

  const list = sorted.slice(0, pageSize);
  const hasMore = sorted.length > pageSize;

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text);
    showToast(_['copied'], 'success');
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
      // Refresh assets + portfolio
      const r = await get<Asset[]>('/assets');
      if (r.success && r.data) {
        const dataAssets = r.data.map(a => ({ ...a, asset_type: 'data' as const }));
        setAllAssets(prev => [...dataAssets, ...prev.filter(a => a.asset_type === 'capability')]);
      }
      loadPortfolio();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  /* 调用 (capability assets) */
  const onInvoke = async (capId: string) => {
    setLoading(true);
    setInvokeResult(null);
    const res = await post<any>('/capability/invoke', {
      capability_id: capId,
      consumer: 'gui_user',
      amount: parseFloat(buyAmt),
      max_price: 100.0,
      input: { text: 'Dashboard invocation test' },
    });
    if (res.success && res.data?.ok) {
      setInvokeResult(res.data);
      showToast(_['invoke-success'], 'success');
    } else {
      showToast(res.data?.error || res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  /* 质押 */
  const onStake = async (validatorId: string) => {
    const amt = parseFloat(stakeAmts[validatorId] || '10000');
    if (!amt || amt <= 0) return;
    setStakingId(validatorId);
    const res = await post<{ success: boolean; staked: number }>('/stake', { validator_id: validatorId, amount: amt });
    if (res.success && res.data?.success) {
      showToast(_['stake-success'], 'success');
      loadValidators();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setStakingId(null);
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
    <div class="page">
      <h1 class="label" style="margin:0 0 4px 0">{_['explore-title']}</h1>
      <p class="caption" style="margin:0">{_['explore-desc']}</p>

      <div class="mb-16" />

      {/* Section tabs */}
      <div class="auto-tabs mb-24">
        <button class={`auto-tab ${exploreTab === 'browse' ? 'active' : ''}`} onClick={() => setExploreTab('browse')}>
          {_['browse-all']}
        </button>
        <button class={`auto-tab ${exploreTab === 'portfolio' ? 'active' : ''}`} onClick={() => setExploreTab('portfolio')}>
          {_['portfolio']}
          {holdings.length > 0 && <span class="auto-tab-count">{holdings.length}</span>}
        </button>
        <button class={`auto-tab ${exploreTab === 'stake' ? 'active' : ''}`} onClick={() => setExploreTab('stake')}>
          {_['stake']}
        </button>
      </div>

      {exploreTab === 'browse' && <>

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
      <div class="search-box-wrap">
        <input
          class="search-box"
          value={q}
          onInput={e => onSearch((e.target as HTMLInputElement).value)}
          placeholder={_['explore-search']}
        />
      </div>

      <div class="mb-24" />

      {/* Tag 过滤 + 排序 */}
      {allTags.length > 0 && (
        <div class="row between mb-24" style="flex-wrap:wrap;gap:12px">
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
          <div class="skeleton" style="height:48px;margin-bottom:8px" />
          <div class="skeleton" style="height:48px;margin-bottom:8px" />
          <div class="skeleton" style="height:48px;margin-bottom:8px" />
        </div>
      ) : list.length === 0 && allAssets.length === 0 ? (
        <div class="center p-0-64">
          <div style="font-size:15px;color:var(--fg-2);margin-bottom:8px">{_['explore-empty']}</div>
          <div class="caption">{_['explore-browse']}</div>
        </div>
      ) : list.length === 0 ? (
        <div class="center p-0-64">
          <div style="font-size:14px;color:var(--fg-2)">{q ? _['inbox-no-match'] : _['explore-empty']}</div>
        </div>
      ) : (
        <div class="explore-list">
          {list.map(a => {
            const isActive = activeId === a.asset_id;
            const isCap = isCapability(a);
            return (
              <div key={a.asset_id} class={`explore-item ${isCap ? 'explore-item-cap' : ''}`}>
                <button class="explore-row" onClick={() => toggleItem(a.asset_id)}>
                  <div class="grow">
                    <div class="explore-name">
                      {isCap && <span class="type-badge cap-badge">⚡</span>}
                      {isCap ? (a.name || maskIdShort(a.asset_id)) : (a.tags?.length ? a.tags.join(' · ') : maskIdShort(a.asset_id))}
                      {isCap && a.version && <span class="version-tag">v{a.version}</span>}
                    </div>
                    <div class="explore-meta">
                      <span class="mono explore-id-inline">{maskIdShort(a.asset_id)}</span>
                      {isCap && a.provider && <span class="explore-owner-inline">{maskOwner(a.provider)}</span>}
                      {!isCap && a.owner && <span class="explore-owner-inline">{maskOwner(a.owner)}</span>}
                    </div>
                  </div>
                  <span class="mono explore-price-prominent">{fmtPrice(a.spot_price)} <span style="font-weight:400;font-size:11px">OAS</span></span>
                  <span class="btn btn-sm btn-ghost">{isCap ? _['invoke'] : _['get-access']}</span>
                </button>

                {/* 内联操作区 */}
                {isActive && (
                  <div class="explore-inline">
                    {isCap ? (
                      /* ── Capability invoke flow ── */
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
                          <div>
                            <label class="label">{_['amount']}</label>
                            <input class="input" type="number" value={buyAmt} onInput={e => setBuyAmt((e.target as HTMLInputElement).value)} min="1" />
                          </div>
                          <button class="btn btn-primary btn-full" onClick={() => onInvoke(a.asset_id)} disabled={loading}>
                            {loading ? _['invoking'] : _['invoke']}
                          </button>
                        </div>
                      ) : (
                        <div class="col gap-8">
                          <div class="kv"><span class="kv-key">{_['pay']}</span><span class="kv-val">{invokeResult.price} OAS</span></div>
                          <div class="kv"><span class="kv-key">{_['shares-minted']}</span><span class="kv-val">{invokeResult.shares_minted}</span></div>
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
                          <div class="kv"><span class="kv-key">{_['price-impact']}</span><span class="kv-val">{quote.price_impact}%</span></div>
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
                          <button class="btn btn-ghost btn-full" style="margin-top:16px" onClick={() => { resetActive(); setBuyAmt('10'); }}>{_['back']}</button>
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

      </>}

      {/* ── Portfolio Section ── */}
      {exploreTab === 'portfolio' && <>
      <h2 class="label" style="margin:0 0 16px 0">{_['portfolio']}</h2>
      {holdingsLoading ? (
        <div class="skeleton" style="height:60px;margin-bottom:8px" />
      ) : holdings.length === 0 ? (
        <div class="center p-0-64">
          <div class="caption mb-8">{_['no-holdings']}</div>
          <div class="caption" style="color:var(--fg-2)">{_['portfolio-hint']}</div>
        </div>
      ) : (
        <div class="portfolio-list">
          {holdings.map(h => (
            <div key={h.asset_id} class="portfolio-row">
              <div class="grow">
                <span class="mono portfolio-id">{maskIdShort(h.asset_id)}</span>
              </div>
              <div class="portfolio-stats">
                <div class="portfolio-stat">
                  <span class="portfolio-stat-label">{_['shares']}</span>
                  <span class="portfolio-stat-val">{h.shares}</span>
                </div>
                <div class="portfolio-stat">
                  <span class="portfolio-stat-label">{_['avg-price']}</span>
                  <span class="portfolio-stat-val">{fmtPrice(h.avg_price)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      </>}

      {/* ── Stake Section ── */}
      {exploreTab === 'stake' && <>
      <h2 class="label" style="margin:0 0 16px 0">{_['stake']}</h2>
      {validators.length === 0 ? (
        <div class="center p-0-64">
          <div class="caption mb-8">{_['no-validators']}</div>
          <div class="caption" style="color:var(--fg-2)">{_['stake-hint']}</div>
        </div>
      ) : (
        <div class="col gap-16">
          {validators.map(v => (
            <div key={v.id} class="card stake-card">
              <div class="kv"><span class="kv-key">{_['validator']}</span><span class="kv-val">{maskIdShort(v.id)}</span></div>
              <div class="kv"><span class="kv-key">{_['staked']}</span><span class="kv-val">{fmtPrice(v.staked)} OAS</span></div>
              <div class="kv"><span class="kv-key">{_['reputation']}</span><span class="kv-val">{v.reputation}</span></div>
              <div class="row gap-8" style="margin-top:12px">
                <input
                  class="input grow"
                  type="number"
                  placeholder={_['stake-amount']}
                  value={stakeAmts[v.id] || ''}
                  onInput={e => setStakeAmts(prev => ({ ...prev, [v.id]: (e.target as HTMLInputElement).value }))}
                  min="1"
                />
                <button class="btn btn-primary" onClick={() => onStake(v.id)} disabled={stakingId === v.id}>
                  {stakingId === v.id ? _['staking'] : _['stake']}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      </>}
    </div>
  );
}
