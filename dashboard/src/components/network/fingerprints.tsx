import { useState } from 'preact/hooks';
import { get } from '../../api/client';
import { showToast, i18n } from '../../store/ui';
import { fmtDate } from '../../utils';
import { Section } from '../section';

export function FingerprintsSection({ forceOpen }: { forceOpen: boolean }) {
  const [fpAssetId, setFpAssetId] = useState('');
  const [fpRecords, setFpRecords] = useState<any[]>([]);
  const [fpLoading, setFpLoading] = useState(false);

  const _ = i18n.value;

  return (
    <Section id="fingerprints" title={_['fingerprint-list']} forceOpen={forceOpen}>
      <div class="net-tool-form net-tool-form-flush">
        <input class="input" value={fpAssetId}
          onInput={e => setFpAssetId((e.target as HTMLInputElement).value)}
          placeholder={_['fingerprint-asset']} />
        <button class="btn btn-primary btn-full" disabled={fpLoading || !fpAssetId.trim()}
          onClick={async () => {
            setFpLoading(true);
            const res = await get<any>(`/fingerprints?asset_id=${encodeURIComponent(fpAssetId.trim())}`);
            if (res.success && res.data) {
              setFpRecords(Array.isArray(res.data) ? res.data : (res.data.records || []));
            } else {
              showToast(res.error || _['error-generic'], 'error');
              setFpRecords([]);
            }
            setFpLoading(false);
          }}>
          {fpLoading ? '...' : _['fingerprint-list']}
        </button>
      </div>
      {fpRecords.length > 0 ? (
        <div class="mt-12">
          {fpRecords.map((r: any, i: number) => (
            <div key={i} class="kv kv-sm">
              <span class="kv-key mono kv-key-xs">{(r.fingerprint || r.hash || '\u2014').slice(0, 16)}...</span>
              <span class="kv-val">
                <span class="mono">{r.caller || r.caller_id || '\u2014'}</span>
                {' \u00b7 '}
                <span>{fmtDate(r.timestamp)}</span>
              </span>
            </div>
          ))}
        </div>
      ) : (
        fpAssetId && !fpLoading && <div class="caption fg-muted mt-8">
          <div class="mb-4">{_['fingerprint-no-records']}</div>
          <div>{_['fingerprint-no-records-hint']}</div>
        </div>
      )}
    </Section>
  );
}
