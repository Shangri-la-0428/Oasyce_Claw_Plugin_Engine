/**
 * Portfolio tab — holdings display
 */
import { useEffect, useState } from 'preact/hooks';
import { get } from '../api/client';
import { i18n } from '../store/ui';
import { maskIdShort, fmtPrice } from '../utils';
import './explore.css';

interface Holding {
  asset_id: string;
  shares: number;
  avg_price: number;
}

export default function ExplorePortfolio() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [holdingsLoading, setHoldingsLoading] = useState(false);

  const _ = i18n.value;

  useEffect(() => {
    loadPortfolio();
  }, []);

  const loadPortfolio = async () => {
    setHoldingsLoading(true);
    const res = await get<Holding[]>('/shares?owner=gui_user');
    if (res.success && Array.isArray(res.data)) setHoldings(res.data);
    setHoldingsLoading(false);
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
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
