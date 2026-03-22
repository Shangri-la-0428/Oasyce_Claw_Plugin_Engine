/**
 * Portfolio tab — holdings display
 */
import { useEffect, useState } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n, walletAddress } from '../store/ui';
import { maskIdShort, maskIdLong, fmtPrice } from '../utils';
import { DisputeForm, MyDisputes } from '../components/dispute-form';
import './explore.css';

interface Holding {
  asset_id: string;
  shares: number;
  avg_price: number;
}

export default function ExplorePortfolio() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [holdingsLoading, setHoldingsLoading] = useState(false);
  const [disputeAssetId, setDisputeAssetId] = useState<string | null>(null);

  /* Sell state */
  const [sellTarget, setSellTarget] = useState<string | null>(null);
  const [sellAmount, setSellAmount] = useState('');
  const [sellSlippage, setSellSlippage] = useState('0.05');
  const [selling, setSelling] = useState(false);

  /* Transaction history state */
  const [transactions, setTransactions] = useState<any[]>([]);
  const [txLoading, setTxLoading] = useState(false);

  /* Access operations state */
  const [accessTarget, setAccessTarget] = useState<string | null>(null);
  const [accessResult, setAccessResult] = useState<any>(null);
  const [accessLoading, setAccessLoading] = useState(false);

  const _ = i18n.value;

  useEffect(() => {
    loadPortfolio();
    loadTransactions();
  }, []);

  /* Close dispute overlay on Escape */
  useEffect(() => {
    if (!disputeAssetId) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setDisputeAssetId(null); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [disputeAssetId]);

  const loadPortfolio = async () => {
    setHoldingsLoading(true);
    const res = await get<Holding[]>(`/shares?owner=${walletAddress()}`);
    if (res.success && Array.isArray(res.data)) setHoldings(res.data);
    setHoldingsLoading(false);
  };

  const loadTransactions = async () => {
    setTxLoading(true);
    const res = await get<any[]>('/transactions');
    if (res.success && Array.isArray(res.data)) setTransactions(res.data);
    setTxLoading(false);
  };

  /* Sell shares */
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
      loadPortfolio();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setSelling(false);
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
    const res = await post(endpoint, { asset_id: assetId, buyer: walletAddress() });
    if (res.success) {
      setAccessResult(res.data);
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
        <div class="skeleton skeleton-md mb-8" />
      ) : holdings.length === 0 ? (
        <div class="center p-0-64">
          <div class="caption mb-8">{_['no-holdings']}</div>
          <div class="caption fg-muted">{_['portfolio-hint']}</div>
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
                <button
                  class="btn btn-sm btn-ghost"
                  onClick={() => setDisputeAssetId(h.asset_id)}
                  title={_['report-issue']}
                >
                  {_['report-issue']}
                </button>
                <button
                  class="btn btn-sm btn-ghost"
                  onClick={() => { setSellTarget(sellTarget === h.asset_id ? null : h.asset_id); setSellAmount(''); setSellSlippage('0.05'); }}
                >
                  {_['sell']}
                </button>
                <button class="btn btn-sm btn-ghost" onClick={() => onAccess(h.asset_id, 'L0')}>{_['access-query']}</button>
                <button class="btn btn-sm btn-ghost" onClick={() => onAccess(h.asset_id, 'L1')}>{_['access-sample']}</button>
                <button class="btn btn-sm btn-ghost" onClick={() => onAccess(h.asset_id, 'L2')}>{_['access-compute']}</button>
                <button class="btn btn-sm btn-ghost" onClick={() => onAccess(h.asset_id, 'L3')}>{_['access-deliver']}</button>
              </div>
              {/* Inline sell form */}
              {sellTarget === h.asset_id && (
                <div class="row gap-8 mt-8">
                  <input
                    class="input grow"
                    type="number"
                    placeholder={_['sell-amount-hint']}
                    value={sellAmount}
                    onInput={e => setSellAmount((e.target as HTMLInputElement).value)}
                    min="0"
                  />
                  <input
                    class="input"
                    type="number"
                    placeholder={_['sell-slippage']}
                    value={sellSlippage}
                    onInput={e => setSellSlippage((e.target as HTMLInputElement).value)}
                    min="0"
                    step="0.01"
                    style={{ maxWidth: '100px' }}
                  />
                  <button class="btn btn-sm btn-ghost" onClick={() => onSell(h.asset_id)} disabled={selling}>
                    {selling ? _['selling'] : _['sell']}
                  </button>
                </div>
              )}
              {/* Access result */}
              {accessTarget === h.asset_id && (accessLoading || accessResult != null) && (
                <div class="mt-8">
                  <div class="kv"><span class="kv-key">{_['access-result']}</span></div>
                  {accessLoading ? (
                    <div class="caption fg-muted">{_['access-op-running']}</div>
                  ) : (
                    <pre class="mono" style={{ whiteSpace: 'pre-wrap', fontSize: '0.85em' }}>{JSON.stringify(accessResult, null, 2)}</pre>
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
          <div class="skeleton skeleton-md mb-8" />
        ) : transactions.length === 0 ? (
          <div class="center p-0-64">
            <div class="caption fg-muted">{_['tx-no-history']}</div>
          </div>
        ) : (
          <div class="col gap-8">
            {transactions.map((tx, i) => (
              <div key={i} class="portfolio-row">
                <div class="kv"><span class="kv-key mono">{maskIdShort(tx.asset_id)}</span></div>
                <span class="mono">{fmtPrice(tx.amount)} OAS</span>
                {tx.type && <span class="caption">{tx.type}</span>}
                {tx.timestamp && <span class="caption fg-muted">{new Date(tx.timestamp * 1000).toLocaleDateString()}</span>}
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
