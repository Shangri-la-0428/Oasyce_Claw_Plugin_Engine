/**
 * Portfolio tab — holdings display
 */
import { useEffect, useState } from 'preact/hooks';
import { useEscapeKey } from '../hooks/useEscapeKey';
import { get, post } from '../api/client';
import { showToast, i18n, walletAddress } from '../store/ui';
import { maskIdShort, fmtPrice, fmtDate } from '../utils';
import { DisputeForm, MyDisputes } from '../components/dispute-form';
import { EmptyState } from '../components/empty-state';
import './explore.css';

interface Holding {
  asset_id: string;
  shares: number;
  avg_price: number;
}

interface Transaction {
  asset_id: string;
  amount: number;
  type?: string;
  timestamp?: number;
}

/** Access result is an opaque server response displayed as JSON */
interface AccessResult {
  [key: string]: unknown;
}

interface Props { onBrowse?: () => void; }

export default function ExplorePortfolio({ onBrowse }: Props) {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [holdingsLoading, setHoldingsLoading] = useState(false);
  const [disputeAssetId, setDisputeAssetId] = useState<string | null>(null);

  /* Sell state */
  const [sellTarget, setSellTarget] = useState<string | null>(null);
  const [sellAmount, setSellAmount] = useState('');
  const [sellSlippage, setSellSlippage] = useState('0.05');
  const [selling, setSelling] = useState(false);

  /* Sell quote state */
  const [quoting, setQuoting] = useState(false);
  const [quote, setQuote] = useState<{ payout_oas: number; protocol_fee: number; burn_amount: number; price_impact_pct: number } | null>(null);

  /* Transaction history state */
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [txLoading, setTxLoading] = useState(false);

  /* Access operations state */
  const [accessTarget, setAccessTarget] = useState<string | null>(null);
  const [accessResult, setAccessResult] = useState<AccessResult | null>(null);
  const [accessLoading, setAccessLoading] = useState(false);

  const _ = i18n.value;

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setHoldingsLoading(true);
      const res = await get<Holding[]>(`/shares?owner=${walletAddress()}`);
      if (!cancelled && res.success && Array.isArray(res.data)) setHoldings(res.data);
      if (!cancelled) setHoldingsLoading(false);

      setTxLoading(true);
      const txRes = await get<Transaction[]>('/transactions');
      if (!cancelled && txRes.success && Array.isArray(txRes.data)) setTransactions(txRes.data);
      if (!cancelled) setTxLoading(false);
    };
    load();
    return () => { cancelled = true; };
  }, []);

  /* Close dispute overlay on Escape */
  useEscapeKey(() => setDisputeAssetId(null), !!disputeAssetId);

  const loadPortfolio = async () => {
    setHoldingsLoading(true);
    const res = await get<Holding[]>(`/shares?owner=${walletAddress()}`);
    if (res.success && Array.isArray(res.data)) setHoldings(res.data);
    setHoldingsLoading(false);
  };

  const loadTransactions = async () => {
    setTxLoading(true);
    const res = await get<Transaction[]>('/transactions');
    if (res.success && Array.isArray(res.data)) setTransactions(res.data);
    setTxLoading(false);
  };

  /* Fetch sell quote */
  const onQuote = async (assetId: string) => {
    const tokens = Number(sellAmount);
    if (!tokens || tokens <= 0) return;
    setQuoting(true);
    setQuote(null);
    const res = await get<{ payout_oas: number; protocol_fee: number; burn_amount: number; price_impact_pct: number }>(
      `/sell/quote?asset_id=${assetId}&seller=${walletAddress()}&tokens=${tokens}`
    );
    if (res.success && res.data) {
      setQuote(res.data);
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setQuoting(false);
  };

  /* Execute sell (after quote confirmation) */
  const onSell = async (assetId: string) => {
    const tokens = Number(sellAmount);
    const slippage = Number(sellSlippage);
    if (!tokens || tokens <= 0) return;
    setSelling(true);
    const res = await post('/sell', {
      asset_id: assetId,
      seller: walletAddress(),
      tokens,
      max_slippage: slippage,
    });
    if (res.success) {
      showToast(_['sell-success'], 'success');
      setSellTarget(null);
      setSellAmount('');
      setSellSlippage('0.05');
      setQuote(null);
      loadPortfolio();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setSelling(false);
  };

  /* Reset quote when amount or target changes */
  const resetSell = (assetId: string) => {
    setSellTarget(sellTarget === assetId ? null : assetId);
    setSellAmount('');
    setSellSlippage('0.05');
    setQuote(null);
  };

  /* Access operations */
  const onAccess = async (assetId: string, level: string) => {
    setAccessTarget(assetId);
    setAccessResult(null);
    setAccessLoading(true);
    const endpoint = level === 'L0' ? '/access/query'
      : level === 'L1' ? '/access/sample'
      : level === 'L2' ? '/access/compute'
      : '/access/deliver';
    const res = await post<AccessResult>(endpoint, { asset_id: assetId, buyer: walletAddress() });
    if (res.success) {
      setAccessResult(res.data ?? null);
    } else {
      showToast(res.error || _['error-generic'], 'error');
      setAccessResult(null);
    }
    setAccessLoading(false);
  };

  return (
    <>
      <h2 class="label-inline mb-16">{_['portfolio']}</h2>
      {holdingsLoading ? (
        <div class="skeleton skeleton-md mb-8" role="status" aria-busy="true" aria-label={_['loading']} />
      ) : holdings.length === 0 ? (
        <EmptyState icon="◇" title={_['no-holdings']} hint={_['portfolio-hint']}>
          {onBrowse && <button class="btn btn-ghost" onClick={onBrowse}>{_['portfolio-browse-cta']}</button>}
        </EmptyState>
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
                <button
                  class="btn btn-sm btn-ghost"
                  onClick={() => setDisputeAssetId(h.asset_id)}
                  title={_['report-issue']}
                >
                  {_['report-issue']}
                </button>
                <button
                  class="btn btn-sm btn-ghost"
                  onClick={() => resetSell(h.asset_id)}
                >
                  {_['sell']}
                </button>
                <button class="btn btn-sm btn-ghost" onClick={() => onAccess(h.asset_id, 'L0')}>{_['access-query']}</button>
                <button class="btn btn-sm btn-ghost" onClick={() => onAccess(h.asset_id, 'L1')}>{_['access-sample']}</button>
                <button class="btn btn-sm btn-ghost" onClick={() => onAccess(h.asset_id, 'L2')}>{_['access-compute']}</button>
                <button class="btn btn-sm btn-ghost" onClick={() => onAccess(h.asset_id, 'L3')}>{_['access-deliver']}</button>
              </div>
              {/* Inline sell form with quote preview */}
              {sellTarget === h.asset_id && (
                <div class="sell-flow mt-8">
                  <div class="row gap-8">
                    <input
                      class="input grow"
                      type="number"
                      placeholder={_['sell-amount-hint']}
                      value={sellAmount}
                      onInput={e => { setSellAmount((e.target as HTMLInputElement).value); setQuote(null); }}
                      min="0"
                    />
                    <input
                      class="input input-narrow"
                      type="number"
                      placeholder={_['sell-slippage']}
                      value={sellSlippage}
                      onInput={e => setSellSlippage((e.target as HTMLInputElement).value)}
                      min="0"
                      step="0.01"
                    />
                    {!quote && (
                      <button class="btn btn-sm btn-ghost" onClick={() => onQuote(h.asset_id)} disabled={quoting || !sellAmount}>
                        {quoting ? _['sell-quoting'] : _['sell-quote']}
                      </button>
                    )}
                  </div>

                  {/* Quote breakdown */}
                  {quote && (
                    <div class="sell-quote-card mt-8">
                      <div class="kv">
                        <span class="kv-key">{_['sell-payout']}</span>
                        <span class="kv-val mono">{fmtPrice(quote.payout_oas)} OAS</span>
                      </div>
                      <div class="kv">
                        <span class="kv-key">{_['sell-fee']}</span>
                        <span class="kv-val mono">{fmtPrice(quote.protocol_fee)} OAS</span>
                      </div>
                      <div class="kv">
                        <span class="kv-key">{_['sell-burn']}</span>
                        <span class="kv-val mono">{fmtPrice(quote.burn_amount)} OAS</span>
                      </div>
                      <div class="kv">
                        <span class="kv-key">{_['sell-impact']}</span>
                        <span class={`kv-val mono ${quote.price_impact_pct > 5 ? 'color-yellow' : ''}`}>
                          {quote.price_impact_pct.toFixed(1)}%
                        </span>
                      </div>
                      {quote.price_impact_pct > 5 && (
                        <div class="sell-impact-warning">{_['sell-impact-warning']}</div>
                      )}
                      <div class="row gap-8 mt-8">
                        <button class="btn btn-sm btn-ghost grow" onClick={() => setQuote(null)}>
                          {_['back']}
                        </button>
                        <button class="btn btn-sm btn-ghost grow" onClick={() => onSell(h.asset_id)} disabled={selling}>
                          {selling ? _['selling'] : _['sell-confirm']}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {/* Access result */}
              {accessTarget === h.asset_id && (accessLoading || accessResult != null) && (
                <div class="mt-8">
                  <div class="kv"><span class="kv-key">{_['access-result']}</span></div>
                  {accessLoading ? (
                    <div class="caption fg-muted">{_['access-op-running']}</div>
                  ) : (
                    <pre class="mono code-block">{JSON.stringify(accessResult, null, 2)}</pre>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Transaction history */}
      <div class="mt-32">
        <h2 class="label-inline mb-16">{_['tx-history']}</h2>
        {txLoading ? (
          <div class="skeleton skeleton-md mb-8" role="status" aria-busy="true" aria-label={_['loading']} />
        ) : transactions.length === 0 ? (
          <EmptyState icon="⇄" title={_['tx-no-history']} hint={_['tx-no-history-hint']} />
        ) : (
          <div class="col gap-8">
            {transactions.map((tx, i) => (
              <div key={i} class="portfolio-row">
                <div class="kv"><span class="kv-key mono">{maskIdShort(tx.asset_id)}</span></div>
                <span class="mono">{fmtPrice(tx.amount)} OAS</span>
                {tx.type && <span class="caption">{tx.type}</span>}
                {tx.timestamp && <span class="caption fg-muted">{fmtDate(tx.timestamp, 'date')}</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Dispute form overlay */}
      {disputeAssetId && (
        <div class="preview-overlay" onClick={() => setDisputeAssetId(null)}>
          <div class="preview-overlay-inner" onClick={e => e.stopPropagation()}>
            <DisputeForm
              assetId={disputeAssetId}
              onClose={() => setDisputeAssetId(null)}
            />
          </div>
        </div>
      )}

      {/* My disputes section */}
      <div class="mt-32">
        <MyDisputes />
      </div>
    </>
  );
}
