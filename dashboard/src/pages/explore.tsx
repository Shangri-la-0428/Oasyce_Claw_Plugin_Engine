/**
 * Explore — 搜索网络上的资产（数据 + 服务），查看报价，获取访问权/调用
 */
import { useEffect, useState, useRef } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n } from '../store/ui';
import type { Asset } from '../store/assets';
import './explore.css';

function maskIdShort(id: string) {
  if (!id || id.length <= 8) return id;
  return id.slice(0, 8) + '••••';
}

function maskIdLong(id: string) {
  if (!id || id.length <= 16) return id;
  return id.slice(0, 16) + '••••';
}

function maskOwner(owner: string) {
  if (!owner || owner.length <= 12) return owner;
  return owner.slice(0, 6) + '••••';
}

function fmtPrice(p: number | undefined | null): string {
  if (p == null) return '--';
  return p >= 1 ? p.toFixed(2) : p.toFixed(4);
}

type AssetFilter = 'all' | 'data' | 'capability';
type SortBy = 'time' | 'value';

export default function Explore() {
  const [q, setQ] = useState('');
  const [allAssets, setAllAssets] = useState<Asset[]>([]);
  const [pageSize, setPageSize] = useState(20);
  const [sortBy, setSortBy] = useState<SortBy>('time');
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<AssetFilter>('all');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [buyAmt, setBuyAmt] = useState('10');
  const [quote, setQuote] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [invokeResult, setInvokeResult] = useState<any>(null);
  const debounceRef = useRef<number>(0);

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
    });
  }, []);

  const onSearch = (val: string) => {
    setQ(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setPageSize(20);
      setActiveId(null);
      setQuote(null);
      setInvokeResult(null);
    }, 300);
  };

  /* 过滤 + 排序 */
  const allTags = [...new Set(allAssets.flatMap(a => a.tags ?? []))];

  const tagCounts = allAssets.reduce<Record<string, number>>((acc, a) => {
    (a.tags ?? []).forEach(tag => { acc[tag] = (acc[tag] || 0) + 1; });
    return acc;
  }, {});

  const filtered = allAssets.filter(a => {
    // Type filter
    if (typeFilter !== 'all' && (a.asset_type || 'data') !== typeFilter) return false;
    // Tag filter
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

  /* 报价 (data assets) */
  const onQuote = async (assetId: string) => {
    setLoading(true);
    const res = await get(`/quote?asset_id=${assetId}&amount=${buyAmt}`);
    if (res.success && res.data) setQuote(res.data);
    else showToast(res.error || 'Failed', 'error');
    setLoading(false);
  };

  /* 购买 (data assets) */
  const onBuy = async (assetId: string) => {
    setLoading(true);
    const res = await post('/buy', { asset_id: assetId, buyer: 'gui_user', amount: parseFloat(buyAmt) });
    if (res.success) {
      showToast('✓', 'success');
      setQuote(null);
      setActiveId(null);
      const r = await get<Asset[]>('/assets');
      if (r.success && r.data) {
        const dataAssets = r.data.map(a => ({ ...a, asset_type: 'data' as const }));
        setAllAssets(prev => [...dataAssets, ...prev.filter(a => a.asset_type === 'capability')]);
      }
    } else {
      showToast(res.error || 'Failed', 'error');
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
      showToast(res.data?.error || res.error || 'Failed', 'error');
    }
    setLoading(false);
  };

  const toggleItem = (id: string) => {
    if (activeId === id) {
      setActiveId(null);
      setQuote(null);
      setInvokeResult(null);
      setBuyAmt('10');
    } else {
      setActiveId(id);
      setQuote(null);
      setInvokeResult(null);
      setBuyAmt('10');
    }
  };

  const isCapability = (a: Asset) => (a.asset_type || 'data') === 'capability';

  return (
    <div class="page">
      <h1 class="heading" style="margin:0 0 4px 0">{_['explore-title']}</h1>
      <p class="caption" style="margin:0">{_['explore-desc']}</p>

      <div style="height:24px" />

      {/* Asset type filter */}
      <div class="row gap-8 mb-16">
        {(['all', 'data', 'capability'] as AssetFilter[]).map(t => (
          <button
            key={t}
            class={`btn btn-sm ${typeFilter === t ? 'btn-active' : 'btn-ghost'}`}
            onClick={() => { setTypeFilter(t); setTagFilter(null); setActiveId(null); }}
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

      <div style="height:24px" />

      {/* Tag 过滤 */}
      {q && allTags.length > 0 && (
        <div class="tag-chips mb-24">
          <button class={`tag-chip ${tagFilter === null ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(null)}>{_['all']}</button>
          {allTags.map(tag => (
            <button key={tag} class={`tag-chip ${tagFilter === tag ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(tagFilter === tag ? null : tag)}>{tag}</button>
          ))}
        </div>
      )}

      {/* 排序 */}
      {q && filtered.length > 0 && (
        <div class="row gap-8 mb-24">
          <button class={`btn btn-sm ${sortBy === 'time' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('time')}>{_['sort-time']}</button>
          <button class={`btn btn-sm ${sortBy === 'value' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('value')}>{_['sort-value']}</button>
        </div>
      )}

      {/* 结果列表 / 分类浏览 / 空状态 */}
      {!q && allTags.length > 0 ? (
        <div>
          <div class="label">{_['categories']}</div>
          <div class="category-grid">
            {Object.entries(tagCounts).sort((a, b) => b[1] - a[1]).map(([tag, count]) => (
              <button key={tag} class="category-card" onClick={() => { setQ(tag); onSearch(tag); }}>
                <span class="category-name">{tag}</span>
                <span class="category-count">{count}</span>
              </button>
            ))}
          </div>
        </div>
      ) : !q && allTags.length === 0 ? (
        <div class="center" style="padding:64px 0">
          <div class="caption">{_['explore-empty']}</div>
        </div>
      ) : list.length === 0 ? (
        <div class="center" style="padding:64px 0">
          <div style="font-size:14px;color:var(--fg-2)">No match</div>
        </div>
      ) : (
        <div class="explore-list">
          {list.map(a => {
            const isActive = activeId === a.asset_id;
            const isCap = isCapability(a);
            return (
              <div key={a.asset_id} class="explore-item">
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
                  <span class="mono explore-price-prominent">{fmtPrice(a.spot_price)}</span>
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
                          <button class="btn btn-ghost btn-full" onClick={() => { setInvokeResult(null); setActiveId(null); }}>{_['back']}</button>
                        </div>
                      )
                    ) : (
                      /* ── Data asset buy flow (unchanged) ── */
                      !quote ? (
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
                          <div>
                            <label class="label">{_['amount']}</label>
                            <input class="input" type="number" value={buyAmt} onInput={e => setBuyAmt((e.target as HTMLInputElement).value)} min="1" />
                          </div>
                          <button class="btn btn-primary btn-full" onClick={() => onQuote(a.asset_id)} disabled={loading}>
                            {loading ? _['quoting'] : _['quote']}
                          </button>
                        </div>
                      ) : (
                        <div>
                          <div class="kv"><span class="kv-key">{_['pay']}</span><span class="kv-val">{quote.payment}</span></div>
                          <div class="kv"><span class="kv-key">{_['receive']}</span><span class="kv-val">{quote.tokens}</span></div>
                          {quote.impact_pct != null && <div class="kv"><span class="kv-key">{_['impact']}</span><span class="kv-val">{quote.impact_pct}%</span></div>}
                          <div class="row gap-16" style="margin-top:24px">
                            <button class="btn btn-ghost grow" onClick={() => setQuote(null)}>{_['back']}</button>
                            <button class="btn btn-primary grow" onClick={() => onBuy(a.asset_id)} disabled={loading}>
                              {loading ? _['buying'] : _['confirm-buy']}
                            </button>
                          </div>
                        </div>
                      )
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {list.length > 0 && (
        <div class="center" style="padding:24px 0">
          {hasMore ? (
            <button class="btn btn-ghost btn-sm" onClick={() => setPageSize(s => s + 20)}>{_['load-more']}</button>
          ) : (
            <span class="caption">{_['no-more']}</span>
          )}
        </div>
      )}
    </div>
  );
}
