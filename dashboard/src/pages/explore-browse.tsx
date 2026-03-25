/**
 * Browse tab — search, type/tag filtering, asset list, tiered access quote/buy, capability invoke
 */
import { useEffect, useState, useRef, useMemo, useLayoutEffect } from 'preact/hooks';
import { useEscapeKey } from '../hooks/useEscapeKey';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { get, post } from '../api/client';
import { showToast, i18n, walletAddress } from '../store/ui';
import type { Asset } from '../store/assets';
import { maskIdShort, maskIdLong, maskOwner, fmtPrice, safePct, safeNum, copyText } from '../utils';
import { EmptyState } from '../components/empty-state';
import DataPreview from '../components/data-preview';
import RegisterForm from '../components/register-form';
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
  shares_minted: number;
}

interface Props {
  subpath?: string;
}

export default function ExploreBrowse({ subpath }: Props) {
  const [q, setQ] = useState('');
  const [allAssets, setAllAssets] = useState<Asset[]>([]);
  const [discoverResults, setDiscoverResults] = useState<Asset[]>([]);
  const [isDiscover, setIsDiscover] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [sortBy, setSortBy] = useState<SortBy>('time');
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<AssetFilter>('all');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<AccessLevel>('L1');
  const [buyStep, setBuyStep] = useState<BuyStep>('form');
  const [accessQuote, setAccessQuote] = useState<AccessQuoteData | null>(null);
  const [buyResult, setBuyResult] = useState<BuyResult | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [buyLoading, setBuyLoading] = useState(false);
  const [invokeLoading, setInvokeLoading] = useState(false);
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [invokeResult, setInvokeResult] = useState<any>(null);
  const [invokeInput, setInvokeInput] = useState('{"text": "hello"}');
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [disputeReason, setDisputeReason] = useState('');
  const [disputeLoading, setDisputeLoading] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [showCapRegister, setShowCapRegister] = useState(false);
  const [showAllTags, setShowAllTags] = useState(false);
  const debounceRef = useRef<number>(0);
  const busyRef = useRef(false);
  const genRef = useRef(0);

  const _ = i18n.value;

  /* 加载数据资产 + capability 资产 */
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      get<Asset[]>('/assets'),
      get<Asset[]>('/capabilities'),
    ]).then(([dataRes, capRes]) => {
      if (cancelled) return;
      const rawData = dataRes.success && Array.isArray(dataRes.data) ? dataRes.data : [];
      const rawCaps = capRes.success && Array.isArray(capRes.data) ? capRes.data : [];
      const dataAssets = rawData.map(a => ({ ...a, asset_type: 'data' as const }));
      const capAssets = rawCaps.map(a => ({ ...a, asset_type: 'capability' as const }));
      setAllAssets([...dataAssets, ...capAssets]);
    }).finally(() => { if (!cancelled) setInitialLoading(false); });

    return () => { cancelled = true; clearTimeout(debounceRef.current); };
  }, []);

  /* Invalidate in-flight async ops on unmount */
  useEffect(() => {
    return () => { genRef.current++; };
  }, []);

  /* Lock body scroll when panel is open */
  useLayoutEffect(() => {
    if (!activeId) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [activeId]);

  /* Close preview overlay on Escape, or close detail panel */
  useEscapeKey(() => setPreviewId(null), !!previewId);
  useEscapeKey(() => resetActive(), !!activeId && !previewId);

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
    setIsDiscover(false);
    clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setPageSize(20);
      resetActive();
    }, 300);
  };

  /** Smart discover — server-side semantic scoring for capabilities */
  const onDiscover = async () => {
    if (!q.trim()) return;
    setDiscoverLoading(true);
    const res = await get<any[]>(`/discover?intents=${encodeURIComponent(q)}&limit=20`);
    if (res.success && Array.isArray(res.data)) {
      setDiscoverResults(res.data.map(d => ({
        asset_id: d.capability_id,
        asset_type: 'capability' as const,
        name: d.name,
        provider: d.provider,
        tags: d.tags,
        spot_price: d.base_price,
        success_rate: d.success_rate,
        _score: d.final_score,
      } as Asset & { _score?: number })));
      setIsDiscover(true);
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setDiscoverLoading(false);
  };

  const resetActive = () => {
    genRef.current++;           // invalidate all in-flight async ops
    setActiveId(null);
    setAccessQuote(null);
    setBuyResult(null);
    setBuyStep('form');
    setSelectedLevel('L1');
    setInvokeResult(null);
    setInvokeInput('{"text": "hello"}');
    setDisputeOpen(false);
    setDisputeReason('');
  };

  /* 过滤 + 排序 (memoized) */
  const allTags = useMemo(
    () => [...new Set(allAssets.flatMap(a => a.tags ?? []))],
    [allAssets]
  );

  /* H4: Limit visible tag filter chips */
  const MAX_VISIBLE_TAGS = 15;
  const visibleTags = showAllTags ? allTags : allTags.slice(0, MAX_VISIBLE_TAGS);
  const hasMoreTags = allTags.length > MAX_VISIBLE_TAGS;

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

  const baseList = isDiscover ? discoverResults : sorted;
  const list = useMemo(() => baseList.slice(0, pageSize), [baseList, pageSize]);
  const hasMore = baseList.length > pageSize;

  /* 获取所有层级报价 — GET /api/access/quote */
  const onFetchQuote = async (assetId: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    const gen = ++genRef.current;
    setQuoteLoading(true);
    try {
      const buyer = walletAddress();
      const res = await get<AccessQuoteData>(
        `/access/quote?asset_id=${encodeURIComponent(assetId)}&buyer=${encodeURIComponent(buyer)}`
      );
      if (gen !== genRef.current) return; // stale response, discard
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
    } finally {
      busyRef.current = false;
      if (gen === genRef.current) setQuoteLoading(false);
    }
  };

  /* 购买访问权 — POST /api/access/buy */
  const onBuyAccess = async (assetId: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    const gen = ++genRef.current;
    setBuyLoading(true);
    try {
      const res = await post<any>('/access/buy', {
        asset_id: assetId,
        buyer: walletAddress(),
        level: selectedLevel,
      });
      if (gen !== genRef.current) return; // stale response, discard
      if (res.success && res.data && res.data.ok) {
        const lq = accessQuote?.levels.find(l => l.level === selectedLevel);
        setBuyResult({
          success: true,
          level: selectedLevel,
          bond: lq?.bond ?? res.data.bond ?? 0,
          liability_days: lq?.liability_days ?? res.data.liability_days ?? 0,
          shares_minted: res.data.shares_minted ?? 0,
        });
        setBuyStep('success');
        showToast(_['buy-success'], 'success');
        // Refresh assets
        const r = await get<Asset[]>('/assets');
        if (gen !== genRef.current) return; // stale after refresh fetch
        if (r.success && r.data) {
          const dataAssets = r.data.map(a => ({ ...a, asset_type: 'data' as const }));
          setAllAssets(prev => [...dataAssets, ...prev.filter(a => a.asset_type === 'capability')]);
        }
      } else {
        showToast(res.data?.error || res.error || _['error-generic'], 'error');
      }
    } finally {
      busyRef.current = false;
      if (gen === genRef.current) setBuyLoading(false);
    }
  };

  /* 调用 (capability assets) — delivery protocol */
  const onInvoke = async (capId: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    const gen = ++genRef.current;
    setInvokeLoading(true);
    setInvokeResult(null);
    try {
      let parsedInput: any = {};
      try { parsedInput = JSON.parse(invokeInput); } catch { parsedInput = { text: invokeInput }; }
      const res = await post<any>('/delivery/invoke', {
        capability_id: capId,
        consumer: walletAddress(),
        input: parsedInput,
      });
      if (gen !== genRef.current) return; // stale response, discard
      if (res.success && res.data?.ok) {
        setInvokeResult(res.data);
        showToast(_['invoke-success'], 'success');
      } else {
        showToast(res.data?.error || res.error || _['error-generic'], 'error');
      }
    } finally {
      busyRef.current = false;
      if (gen === genRef.current) setInvokeLoading(false);
    }
  };

  /* 争议 (invocation dispute via delivery API) */
  const onDispute = async (invocationId: string) => {
    if (!disputeReason.trim()) return;
    setDisputeLoading(true);
    try {
      const res = await post<any>(`/delivery/invocation/${invocationId}/dispute`, {
        reason: disputeReason.trim(),
      });
      if (res.success && res.data?.ok) {
        showToast(_['dispute-success'] || _['invocation_disputed'], 'success');
        setDisputeOpen(false);
        setDisputeReason('');
        if (invokeResult) setInvokeResult({ ...invokeResult, _disputed: true });
      } else {
        showToast(res.data?.error || res.error || _['error-generic'], 'error');
      }
    } finally {
      setDisputeLoading(false);
    }
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
      setDisputeOpen(false);
      setDisputeReason('');
    }
  };

  const isCapability = (a: Asset) => (a.asset_type || 'data') === 'capability';
  const activeAsset = activeId ? allAssets.find(a => a.asset_id === activeId) || discoverResults.find(a => a.asset_id === activeId) : null;

  // H2: Focus trap for detail panel
  const panelRef = useFocusTrap(!!activeAsset);

  // H3: Focus trap for preview overlay
  const previewRef = useFocusTrap(!!previewId);

  return (
    <>
      {/* Asset type filter + capability register entry */}
      <div class="row gap-8 mb-16 between">
        <div class="row gap-8">
          {(['all', 'data', 'capability'] as AssetFilter[]).map(t => (
            <button
              key={t}
              class={`btn btn-sm ${typeFilter === t ? 'btn-active' : 'btn-ghost'}`}
              onClick={() => { setTypeFilter(t); setTagFilter(null); setIsDiscover(false); resetActive(); setShowCapRegister(false); }}
            >
              {_[`type-${t}`]}
            </button>
          ))}
        </div>
        {typeFilter === 'capability' && (
          <button
            class={`btn btn-sm ${showCapRegister ? 'btn-active' : 'btn-ghost'}`}
            onClick={() => setShowCapRegister(!showCapRegister)}
          >
            + {_['earnings-empty-cta']}
          </button>
        )}
      </div>

      {/* Capability registration form (collapsible) */}
      {showCapRegister && (
        <div class="mb-24">
          <RegisterForm
            mode="capability"
            compact
            onSuccess={() => {
              setShowCapRegister(false);
              // Refresh asset list
              get<Asset[]>('/capabilities').then(res => {
                if (res.success && Array.isArray(res.data)) {
                  setAllAssets(prev => {
                    const ids = new Set(prev.map(a => a.asset_id));
                    const newOnes = res.data!.filter(a => !ids.has(a.asset_id));
                    return [...newOnes, ...prev];
                  });
                }
              });
            }}
          />
        </div>
      )}

      {/* 搜索框 */}
      <div class="search-box-wrap mb-24">
        <div class="row gap-8">
          <input
            class="search-box grow"
            value={q}
            onInput={e => onSearch((e.target as HTMLInputElement).value)}
            placeholder={typeFilter === 'capability' ? _['discover-hint'] : _['explore-search']}
          />
          {typeFilter === 'capability' && q.trim() && (
            <button class={`btn btn-sm ${isDiscover ? 'btn-active' : 'btn-ghost'}`} onClick={onDiscover} disabled={discoverLoading}>
              {_['discover']}
            </button>
          )}
        </div>
        {isDiscover && (
          <div class="caption fg-muted mt-4">
            {_['discover-results'] || `${discoverResults.length} results ranked by relevance`}
          </div>
        )}
      </div>

      {/* Tag 过滤 + 排序 */}
      {allTags.length > 0 && (
        <div class="row between mb-24 wrap gap-12">
          <div class="tag-chips">
            <button class={`tag-chip ${tagFilter === null ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(null)}>{_['all']}</button>
            {visibleTags.map(tag => (
              <button key={tag} class={`tag-chip ${tagFilter === tag ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(tagFilter === tag ? null : tag)}>{tag}</button>
            ))}
            {hasMoreTags && !showAllTags && (
              <button class="tag-chip" onClick={() => setShowAllTags(true)}>+{allTags.length - MAX_VISIBLE_TAGS}</button>
            )}
          </div>
          <div class="row gap-8">
            <button class={`btn btn-sm ${sortBy === 'time' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('time')}>{_['sort-time']}</button>
            <button class={`btn btn-sm ${sortBy === 'value' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('value')}>{_['sort-value']}</button>
          </div>
        </div>
      )}

      {/* 结果列表 / 空状态 */}
      {initialLoading ? (
        <div role="status" aria-busy="true" aria-label={_['loading']}>
          <div class="skeleton skeleton-sm mb-8" />
          <div class="skeleton skeleton-sm mb-8" />
          <div class="skeleton skeleton-sm mb-8" />
        </div>
      ) : list.length === 0 && allAssets.length === 0 ? (
        <EmptyState icon="⌕" title={_['explore-empty']} hint={_['explore-browse']}>
          <div class="quickstart">
            <div class="quickstart-title">{_['explore-quickstart']}</div>
            <div class="quickstart-hint">{_['explore-quickstart-hint']}</div>
            <div class="quickstart-cmds">
              <div class="quickstart-cmd">
                <span class="quickstart-cmd-text">oas demo</span>
                <span class="quickstart-cmd-desc">{_['explore-qs-demo']}</span>
              </div>
              <div class="quickstart-cmd">
                <span class="quickstart-cmd-text">oas register &lt;file&gt;</span>
                <span class="quickstart-cmd-desc">{_['explore-qs-register']}</span>
              </div>
              <div class="quickstart-cmd">
                <span class="quickstart-cmd-text">oas capability register</span>
                <span class="quickstart-cmd-desc">{_['explore-qs-capability']}</span>
              </div>
            </div>
          </div>
        </EmptyState>
      ) : list.length === 0 ? (
        <EmptyState icon={q ? '∅' : '⌕'} title={q ? _['inbox-no-match'] : _['explore-empty']} />
      ) : (
        <div class="item-list">
          {list.map(a => {
            const isActive = activeId === a.asset_id;
            const isCap = isCapability(a);
            return (
              <div key={a.asset_id} class={`explore-item ${isCap ? 'explore-item-cap' : ''} ${isActive ? 'explore-item-selected' : ''}`}>
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
                      <span class="mono item-id-inline">{maskIdShort(a.asset_id)}</span>
                      {isCap && a.provider && <span class="item-owner-inline">{maskOwner(a.provider)}</span>}
                      {!isCap && a.owner && <span class="item-owner-inline">{maskOwner(a.owner)}</span>}
                    </div>
                  </div>
                  <span class="mono item-price">{fmtPrice(a.spot_price)} <span class="oas-unit">OAS</span></span>
                  <button class="btn btn-sm btn-ghost" onClick={(e) => { e.stopPropagation(); setPreviewId(a.asset_id); }}>{_['preview']}</button>
                  <span class="btn btn-sm btn-ghost">{isCap ? _['invoke'] : _['get-access']}</span>
                </button>
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
          <div class="preview-overlay-inner" ref={previewRef} onClick={e => e.stopPropagation()}>
            <DataPreview assetId={previewId} onClose={() => setPreviewId(null)} />
          </div>
        </div>
      )}

      {/* ── Detail side panel ── */}
      {activeAsset && (() => {
        const a = activeAsset;
        const isCap = isCapability(a);
        return (
          <>
            <div class="explore-panel-backdrop" onClick={resetActive} />
            <aside class="explore-panel" ref={panelRef} role="dialog" aria-label={a.name || a.asset_id}>
              <div class="explore-panel-header">
                <div class="explore-panel-title">
                  {isCap && <span class="type-badge cap-badge">⚡</span>}
                  {isCap ? (a.name || maskIdShort(a.asset_id)) : (a.tags?.length ? a.tags.join(' · ') : maskIdShort(a.asset_id))}
                </div>
                <button class="btn btn-sm btn-ghost" onClick={resetActive} aria-label="Close">✕</button>
              </div>

              <div class="explore-panel-body">
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
                      {a.total_calls != null && (
                        <div class="row gap-16 wrap">
                          <div class="kv"><span class="kv-key">{_['cap-total-calls']}</span><span class="kv-val">{a.total_calls}</span></div>
                          {a.success_rate != null && <div class="kv"><span class="kv-key">{_['cap-success-rate']}</span><span class="kv-val">{safePct(a.success_rate)}</span></div>}
                          {a.avg_latency_ms != null && <div class="kv"><span class="kv-key">{_['cap-avg-latency']}</span><span class="kv-val">{safeNum(a.avg_latency_ms, 0)} ms</span></div>}
                        </div>
                      )}
                      <div class="kv"><span class="kv-key">{_['spot-price']}</span><span class="kv-val mono">{fmtPrice(a.spot_price)} OAS</span></div>
                      <div>
                        <label class="label">{_['cap-invoke-input']}</label>
                        <textarea class="input input-textarea-mono" value={invokeInput}
                          onInput={e => setInvokeInput((e.target as HTMLTextAreaElement).value)}
                          placeholder={_['cap-invoke-input-hint']} />
                      </div>
                      <button class="btn btn-primary btn-full" onClick={() => onInvoke(a.asset_id)} disabled={invokeLoading}>
                        {invokeLoading ? _['invoking'] : _['invoke']}
                      </button>
                    </div>
                  ) : (
                    <div class="col gap-8">
                      {/* Invocation ID */}
                      {invokeResult.invocation_id && (
                        <div class="kv">
                          <span class="kv-key">{_['id']}</span>
                          <span class="kv-val">
                            <span class="masked">
                              <span class="mono">{maskIdLong(invokeResult.invocation_id)}</span>
                              <button class="btn-copy" onClick={() => copyText(invokeResult.invocation_id)}>{_['copy']}</button>
                            </span>
                          </span>
                        </div>
                      )}
                      {/* Status */}
                      <div class="kv">
                        <span class="kv-key">{_['status'] || 'Status'}</span>
                        <span class={`kv-val badge ${invokeResult._disputed ? 'badge-red' : 'badge-green'}`}>
                          {invokeResult._disputed ? (_['invocation_disputed']) : (_['invoke-success'])}
                        </span>
                      </div>
                      {invokeResult.price != null && <div class="kv"><span class="kv-key">{_['pay']}</span><span class="kv-val mono">{invokeResult.price} OAS</span></div>}
                      {invokeResult.shares_minted != null && <div class="kv"><span class="kv-key">{_['shares-minted']}</span><span class="kv-val">{invokeResult.shares_minted}</span></div>}
                      {invokeResult.result != null && (
                        <div class="kv">
                          <span class="kv-key">{_['invoke-result']}</span>
                          <span class="kv-val mono invoke-result-val">{typeof invokeResult.result === 'string' ? invokeResult.result : JSON.stringify(invokeResult.result)}</span>
                        </div>
                      )}
                      {invokeResult.usage && (
                        <div class="kv">
                          <span class="kv-key">Usage</span>
                          <span class="kv-val mono">{typeof invokeResult.usage === 'string' ? invokeResult.usage : JSON.stringify(invokeResult.usage)}</span>
                        </div>
                      )}

                      {/* Challenge window: dispute option */}
                      {invokeResult.invocation_id && !invokeResult._disputed && (
                        !disputeOpen ? (
                          <button class="btn btn-ghost btn-full color-red" onClick={() => setDisputeOpen(true)}>
                            {_['dispute']}
                          </button>
                        ) : (
                          <div class="col gap-8 divider-top">
                            <label class="label color-red">{_['challenge_window']}</label>
                            <textarea class="input input-textarea-mono" rows={3} value={disputeReason}
                              onInput={e => setDisputeReason((e.target as HTMLTextAreaElement).value)}
                              placeholder={_['dispute-reason-hint']} />
                            <div class="row gap-8">
                              <button class="btn btn-ghost grow" onClick={() => { setDisputeOpen(false); setDisputeReason(''); }}>{_['back']}</button>
                              <button class="btn btn-primary grow bg-red" disabled={disputeLoading || !disputeReason.trim()}
                                onClick={() => onDispute(invokeResult.invocation_id)}>
                                {disputeLoading ? (_['dispute-submitting']) : (_['dispute-confirm'])}
                              </button>
                            </div>
                          </div>
                        )
                      )}

                      <button class="btn btn-ghost btn-full" onClick={() => { setInvokeResult(null); resetActive(); }}>{_['back']}</button>
                    </div>
                  )
                ) : (
                  /* ── Data asset: tiered access flow ── */
                  buyStep === 'form' ? (
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
                      {a.owner && (
                        <div class="kv"><span class="kv-key">{_['owner']}</span><span class="kv-val">{maskOwner(a.owner)}</span></div>
                      )}
                      {a.tags && a.tags.length > 0 && (
                        <div class="kv"><span class="kv-key">{_['tags']}</span><span class="kv-val">{a.tags.join(', ')}</span></div>
                      )}
                      <div class="kv"><span class="kv-key">{_['type']}</span><span class="kv-val">{_['asset-type-data']}</span></div>
                      <div class="kv"><span class="kv-key">{_['spot-price']}</span><span class="kv-val">{fmtPrice(a.spot_price)} OAS</span></div>

                      <button class="btn btn-primary btn-full" onClick={() => onFetchQuote(a.asset_id)} disabled={quoteLoading}>
                        {quoteLoading ? _['quoting'] : _['quote']}
                      </button>
                    </div>
                  ) : buyStep === 'quoted' && accessQuote ? (
                    <div class="col gap-12">
                      <div class="row gap-16 wrap">
                        <div class="kv"><span class="kv-key">{_['al-reputation']}</span><span class="kv-val">{accessQuote.reputation ?? '--'}</span></div>
                        {accessQuote.risk_level && <div class="kv"><span class="kv-key">{_['al-risk']}</span><span class="kv-val badge">{accessQuote.risk_level}</span></div>}
                        {accessQuote.max_access_level && <div class="kv"><span class="kv-key">{_['al-max']}</span><span class="kv-val">{accessQuote.max_access_level}</span></div>}
                      </div>

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
                        <button class="btn btn-primary grow" onClick={() => onBuyAccess(a.asset_id)} disabled={buyLoading}>
                          {buyLoading ? _['buying'] : _['confirm-buy']}
                        </button>
                      </div>
                    </div>
                  ) : buyStep === 'success' && buyResult ? (
                    <div class="col gap-8">
                      <div class="buy-success-banner">{_['buy-success']}</div>
                      {buyResult.shares_minted > 0 && (
                        <div class="kv"><span class="kv-key">{_['shares-minted']}</span><span class="kv-val mono">{buyResult.shares_minted}</span></div>
                      )}
                      <div class="kv"><span class="kv-key">{_['al-granted']}</span><span class="kv-val">{buyResult.level}</span></div>
                      <div class="kv"><span class="kv-key">{_['al-bond-paid']}</span><span class="kv-val mono">{fmtPrice(buyResult.bond)} OAS</span></div>
                      {buyResult.liability_days > 0 && (
                        <div class="kv"><span class="kv-key">{_['al-liability']}</span><span class="kv-val">{buyResult.liability_days} {_['al-days']}</span></div>
                      )}
                      <button class="btn btn-ghost btn-full mt-16" onClick={resetActive}>{_['back']}</button>
                    </div>
                  ) : null
                )}
              </div>
            </aside>
          </>
        );
      })()}
    </>
  );
}
