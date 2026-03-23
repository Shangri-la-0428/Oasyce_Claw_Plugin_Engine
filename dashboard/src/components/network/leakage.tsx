import { useState } from 'preact/hooks';
import { get, post } from '../../api/client';
import { showToast, i18n } from '../../store/ui';
import { Section } from '../section';

export function LeakageSection({ forceOpen }: { forceOpen: boolean }) {
  const [lkAgentId, setLkAgentId] = useState('');
  const [lkAssetId, setLkAssetId] = useState('');
  const [lkChecking, setLkChecking] = useState(false);
  const [lkResult, setLkResult] = useState<any>(null);
  const [lkResetting, setLkResetting] = useState(false);

  const _ = i18n.value;

  return (
    <Section id="leakage" title={_['leakage']} desc={_['leakage-desc']} forceOpen={forceOpen}>
      <div class="net-tool-form net-tool-form-flush">
        <label class="label">{_['leakage-agent']}</label>
        <input class="input" value={lkAgentId}
          onInput={e => setLkAgentId((e.target as HTMLInputElement).value)}
          placeholder={_['leakage-agent']} />
        <label class="label">{_['leakage-asset']}</label>
        <input class="input" value={lkAssetId}
          onInput={e => setLkAssetId((e.target as HTMLInputElement).value)}
          placeholder={_['leakage-asset']} />
        <div class="row gap-8">
          <button class="btn btn-primary grow" disabled={lkChecking || !lkAgentId.trim() || !lkAssetId.trim()}
            onClick={async () => {
              setLkChecking(true); setLkResult(null);
              const res = await get<any>(`/leakage?agent_id=${encodeURIComponent(lkAgentId.trim())}&asset_id=${encodeURIComponent(lkAssetId.trim())}`);
              if (res.success && res.data) {
                setLkResult(res.data);
              } else {
                showToast(res.error || _['error-generic'], 'error');
              }
              setLkChecking(false);
            }}>
            {lkChecking ? _['leakage-checking'] : _['leakage-check']}
          </button>
          <button class="btn btn-ghost grow" disabled={lkResetting || !lkAgentId.trim() || !lkAssetId.trim()}
            onClick={async () => {
              setLkResetting(true);
              const res = await post<any>('/leakage/reset', {
                agent_id: lkAgentId.trim(),
                asset_id: lkAssetId.trim(),
              });
              if (res.success) {
                showToast(_['leakage-reset-success'], 'success');
                setLkResult(null);
              } else {
                showToast(res.error || _['error-generic'], 'error');
              }
              setLkResetting(false);
            }}>
            {lkResetting ? _['leakage-resetting'] : _['leakage-reset']}
          </button>
        </div>
      </div>

      {lkResult && (
        <div class="net-tool-result mt-12">
          <div class="kv"><span class="kv-key">{_['leakage-remaining']}</span><span class="kv-val mono">{lkResult.remaining}</span></div>
          <div class="kv"><span class="kv-key">{_['leakage-used']}</span><span class="kv-val mono">{lkResult.used}</span></div>
          <div class="kv"><span class="kv-key">{_['leakage-budget-total']}</span><span class="kv-val mono">{lkResult.budget}</span></div>
          <div class="kv"><span class="kv-key">{_['leakage-queries']}</span><span class="kv-val mono">{lkResult.queries}</span></div>
          <div class="kv">
            <span class="kv-key">{_['leakage-exhausted']}</span>
            <span class={`kv-val mono ${lkResult.exhausted ? 'color-red' : 'color-green'}`}>
              {lkResult.exhausted ? _['yes'] : _['no']}
            </span>
          </div>
        </div>
      )}
    </Section>
  );
}
