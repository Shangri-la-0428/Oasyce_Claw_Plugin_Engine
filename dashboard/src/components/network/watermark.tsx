import { useState } from 'preact/hooks';
import { get, post } from '../../api/client';
import { showToast, i18n } from '../../store/ui';
import { fmtDate } from '../../utils';
import { Section } from '../section';

type WmTool = null | 'embed' | 'extract' | 'trace';

export function WatermarkSection({ forceOpen }: { forceOpen: boolean }) {
  const [activeTool, setActiveTool] = useState<WmTool>(null);
  const [wmFilePath, setWmFilePath] = useState('');
  const [wmCallerId, setWmCallerId] = useState('');
  const [wmAssetId, setWmAssetId] = useState('');
  const [wmLoading, setWmLoading] = useState(false);
  const [wmResult, setWmResult] = useState<any>(null);

  const _ = i18n.value;

  const selectTool = (tool: WmTool) => {
    setActiveTool(activeTool === tool ? null : tool);
    setWmResult(null); setWmFilePath(''); setWmCallerId(''); setWmAssetId('');
  };

  const onEmbed = async () => {
    if (!wmFilePath.trim()) return;
    setWmLoading(true); setWmResult(null);
    const res = await post<any>('/fingerprint/embed', { file_path: wmFilePath.trim(), caller_id: wmCallerId.trim() || undefined });
    if (res.success && res.data) { setWmResult(res.data); showToast(_['wm-embed-btn'], 'success'); }
    else showToast(res.error || _['error-generic'], 'error');
    setWmLoading(false);
  };

  const onExtract = async () => {
    if (!wmFilePath.trim()) return;
    setWmLoading(true); setWmResult(null);
    const res = await post<any>('/fingerprint/extract', { file_path: wmFilePath.trim() });
    if (res.success && res.data) setWmResult(res.data);
    else showToast(res.error || _['error-generic'], 'error');
    setWmLoading(false);
  };

  const onTrace = async () => {
    if (!wmAssetId.trim()) return;
    setWmLoading(true); setWmResult(null);
    const res = await get<any>(`/fingerprint/distributions?asset_id=${encodeURIComponent(wmAssetId.trim())}`);
    if (res.success && res.data) setWmResult(res.data);
    else showToast(res.error || _['error-generic'], 'error');
    setWmLoading(false);
  };

  return (
    <Section id="watermark" title={_['net-watermark']} desc={_['net-watermark-desc']} forceOpen={forceOpen}>
      <div class="net-tools">
        <button class={`nav-item ${activeTool === 'embed' ? 'nav-item-active' : ''}`} onClick={() => selectTool('embed')}>
          <span class="nav-item-title">{_['net-embed']} {activeTool === 'embed' ? '\u2193' : '\u2192'}</span>
          <span class="nav-item-desc">{_['net-embed-desc']}</span>
        </button>
        {activeTool === 'embed' && (
          <div class="net-tool-form">
            <input class="input" value={wmFilePath} onInput={e => setWmFilePath((e.target as HTMLInputElement).value)} placeholder={_['wm-file-path']} />
            <input class="input" value={wmCallerId} onInput={e => setWmCallerId((e.target as HTMLInputElement).value)} placeholder={_['wm-caller-id']} />
            <button class="btn btn-primary btn-full" onClick={onEmbed} disabled={wmLoading || !wmFilePath.trim()}>
              {wmLoading ? _['wm-embedding'] : _['wm-embed-btn']}
            </button>
            {wmResult && (
              <div class="net-tool-result">
                {wmResult.watermarked_path && <div class="kv"><span class="kv-key">{_['wm-watermarked-path']}</span><span class="kv-val mono kv-val-xs">{wmResult.watermarked_path}</span></div>}
                {wmResult.fingerprint && <div class="kv"><span class="kv-key">{_['wm-fingerprint']}</span><span class="kv-val mono kv-val-xs-nowrap">{wmResult.fingerprint.slice(0, 16)}...</span></div>}
              </div>
            )}
          </div>
        )}

        <button class={`nav-item ${activeTool === 'extract' ? 'nav-item-active' : ''}`} onClick={() => selectTool('extract')}>
          <span class="nav-item-title">{_['net-extract']} {activeTool === 'extract' ? '\u2193' : '\u2192'}</span>
          <span class="nav-item-desc">{_['net-extract-desc']}</span>
        </button>
        {activeTool === 'extract' && (
          <div class="net-tool-form">
            <input class="input" value={wmFilePath} onInput={e => setWmFilePath((e.target as HTMLInputElement).value)} placeholder={_['wm-file-path']} />
            <button class="btn btn-primary btn-full" onClick={onExtract} disabled={wmLoading || !wmFilePath.trim()}>
              {wmLoading ? _['wm-extracting'] : _['wm-extract-btn']}
            </button>
            {wmResult && (
              <div class="net-tool-result">
                {wmResult.fingerprint && <div class="kv"><span class="kv-key">{_['wm-fingerprint']}</span><span class="kv-val mono kv-val-xs-nowrap">{wmResult.fingerprint}</span></div>}
                {wmResult.caller_id && <div class="kv"><span class="kv-key">{_['wm-caller']}</span><span class="kv-val mono">{wmResult.caller_id}</span></div>}
                {wmResult.timestamp && <div class="kv"><span class="kv-key">{_['wm-timestamp']}</span><span class="kv-val">{fmtDate(wmResult.timestamp)}</span></div>}
                {!wmResult.fingerprint && !wmResult.caller_id && <div class="caption fg-muted">{_['wm-no-records']}</div>}
              </div>
            )}
          </div>
        )}

        <button class={`nav-item ${activeTool === 'trace' ? 'nav-item-active' : ''}`} onClick={() => selectTool('trace')}>
          <span class="nav-item-title">{_['net-trace']} {activeTool === 'trace' ? '\u2193' : '\u2192'}</span>
          <span class="nav-item-desc">{_['net-trace-desc']}</span>
        </button>
        {activeTool === 'trace' && (
          <div class="net-tool-form">
            <input class="input" value={wmAssetId} onInput={e => setWmAssetId((e.target as HTMLInputElement).value)} placeholder={_['wm-asset-id']} />
            <button class="btn btn-primary btn-full" onClick={onTrace} disabled={wmLoading || !wmAssetId.trim()}>
              {wmLoading ? _['wm-listing'] : _['wm-list-btn']}
            </button>
            {wmResult && (
              <div class="net-tool-result">
                {Array.isArray(wmResult.distributions) && wmResult.distributions.length > 0 ? (
                  wmResult.distributions.map((d: any, i: number) => (
                    <div key={i} class="kv">
                      <span class="kv-key mono kv-key-xs">{d.caller_id?.slice(0, 12) || '\u2014'}</span>
                      <span class="kv-val">{fmtDate(d.timestamp)}</span>
                    </div>
                  ))
                ) : (
                  <div class="caption fg-muted">
                    <div class="mb-4">{_['wm-no-records']}</div>
                    <div>{_['wm-no-records-hint']}</div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}
