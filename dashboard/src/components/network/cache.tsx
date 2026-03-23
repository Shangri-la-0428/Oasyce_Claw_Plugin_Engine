import { useState, useEffect } from 'preact/hooks';
import { get, post } from '../../api/client';
import { showToast, i18n } from '../../store/ui';
import { Section } from '../section';

export function CacheSection({ forceOpen }: { forceOpen: boolean }) {
  const [cacheStats, setCacheStats] = useState<any>(null);
  const [cacheLoading, setCacheLoading] = useState(false);
  const [cachePurging, setCachePurging] = useState(false);

  const _ = i18n.value;

  useEffect(() => {
    let cancelled = false;
    setCacheLoading(true);
    get<any>('/cache/stats').then(res => {
      if (cancelled) return;
      if (res.success && res.data) setCacheStats(res.data);
      setCacheLoading(false);
    }).catch(() => { if (!cancelled) setCacheLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <Section id="cache" title={_['cache']} desc={_['cache-stats']} forceOpen={forceOpen}>
      {cacheLoading && <div class="caption fg-muted">{_['cache-stats']}...</div>}

      {!cacheLoading && cacheStats && (
        <div>
          <div class="kv"><span class="kv-key">{_['cache-total']}</span><span class="kv-val mono">{cacheStats.total}</span></div>
          <div class="kv"><span class="kv-key">{_['cache-active']}</span><span class="kv-val mono">{cacheStats.active}</span></div>
          <div class="kv"><span class="kv-key">{_['cache-expired']}</span><span class="kv-val mono">{cacheStats.expired}</span></div>
          {cacheStats.db_path && (
            <div class="kv"><span class="kv-key">{_['cache-db-path']}</span><span class="kv-val mono kv-val-xs">{cacheStats.db_path}</span></div>
          )}
          <button class="btn btn-primary btn-full mt-12" disabled={cachePurging}
            onClick={async () => {
              setCachePurging(true);
              const res = await post<any>('/cache/purge', {});
              if (res.success) {
                showToast(_['cache-purge-success'], 'success');
                const sRes = await get<any>('/cache/stats');
                if (sRes.success && sRes.data) setCacheStats(sRes.data);
              } else {
                showToast(res.error || _['error-generic'], 'error');
              }
              setCachePurging(false);
            }}>
            {cachePurging ? _['cache-purging'] : _['cache-purge']}
          </button>
        </div>
      )}

      {!cacheLoading && !cacheStats && (
        <div class="caption fg-muted">{_['cache-stats']}...</div>
      )}
    </Section>
  );
}
